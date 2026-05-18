"""Final output shaping — Sheets-friendly CSVs in three shapes.

- Adds `abstract_oneliner` / `papers_with_abstract` columns to every CSV
- Re-exports with csv.QUOTE_ALL so newlines/commas don't break Sheets import
- Generates *_long.csv (one row per author×paper) and
                 *_wide_papers.csv (paper_N_title/url/abstract columns)
"""
import argparse, csv, json, os, re
import pandas as pd


def first_sentence(abstract: str, max_chars: int = 220) -> str:
    if not abstract: return ""
    s = re.sub(r"\s+", " ", abstract).strip()
    parts = re.split(r"(?<=\.)\s+", s)
    sentence = parts[0] if parts else s
    if len(sentence) < 30 and len(parts) > 1:
        sentence = parts[0] + " " + parts[1]
    return sentence[:max_chars].rstrip(",;") + ("…" if len(sentence) > max_chars else "")


def export_quoted(path):
    df = pd.read_csv(path)
    df.to_csv(path, index=False, quoting=csv.QUOTE_ALL)


def expand_brief(titles_str, title_to_oneliner, title_to_url):
    if pd.isna(titles_str): return ""
    titles = [t.strip() for t in str(titles_str).split(" | ") if t.strip()]
    out = []
    for t in titles:
        ol = title_to_oneliner.get(t, "")
        url = title_to_url.get(t, "")
        out.append(f"{t} — {ol} ({url})" if ol else f"{t} ({url})")
    return "\n".join(out)


def make_long(in_path, out_path, title_to_oneliner, title_to_url):
    df = pd.read_csv(in_path)
    df["paper_titles"] = df["paper_titles"].fillna("")
    rows = []
    for _, r in df.iterrows():
        titles = [t.strip() for t in r["paper_titles"].split(" | ") if t.strip()]
        for t in titles:
            base = r.drop(["paper_titles", "papers_with_abstract"], errors="ignore").to_dict()
            base["paper_title"] = t
            base["paper_url"] = title_to_url.get(t, "")
            base["abstract_oneliner"] = title_to_oneliner.get(t, "")
            rows.append(base)
    out = pd.DataFrame(rows)
    front = [c for c in out.columns if c not in ("paper_title","paper_url","abstract_oneliner")]
    out = out[front + ["paper_title","paper_url","abstract_oneliner"]]
    out.to_csv(out_path, index=False, quoting=csv.QUOTE_ALL)
    return out


def make_wide_papers(long_path, out_path):
    df = pd.read_csv(long_path)
    grouped = df.groupby("author_name", sort=False)
    static_cols = [c for c in df.columns if c not in ("paper_title","paper_url","abstract_oneliner")]
    max_papers = int(df.groupby("author_name").size().max())
    rows = []
    for _, g in grouped:
        rec = {c: g.iloc[0][c] for c in static_cols}
        rec["num_papers"] = len(g)
        for i, (_, p) in enumerate(g.iterrows(), 1):
            rec[f"paper_{i}_title"] = p["paper_title"]
            rec[f"paper_{i}_url"] = p["paper_url"]
            rec[f"paper_{i}_abstract"] = p["abstract_oneliner"]
        rows.append(rec)
    out = pd.DataFrame(rows)
    ordered = static_cols + ["num_papers"]
    for i in range(1, max_papers+1):
        ordered += [f"paper_{i}_title", f"paper_{i}_url", f"paper_{i}_abstract"]
    out = out[ordered]
    out.to_csv(out_path, index=False, quoting=csv.QUOTE_ALL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    conf = cfg["conference"].lower() + str(cfg["year"])

    papers = json.load(open(os.path.join(out_dir, "papers_matched.json")))
    title_to_oneliner = {p["title"]: first_sentence(p.get("abstract","")) for p in papers}
    title_to_url = {p["title"]: p["url"] for p in papers}

    # 1) abstract_oneliner per row on candidates.csv
    p = os.path.join(out_dir, f"{conf}_candidates.csv")
    df = pd.read_csv(p)
    df["abstract_oneliner"] = df["paper_title"].map(title_to_oneliner).fillna("")
    df.to_csv(p, index=False, quoting=csv.QUOTE_ALL)
    print(f"  {conf}_candidates.csv: abstract_oneliner added")

    # 2) papers_with_abstract on author-level CSVs
    for f in [f"{conf}_unique_authors.csv", f"{conf}_authors_arxiv.csv",
              f"{conf}_filtered.csv", f"{conf}_unknown_country.csv",
              f"{conf}_shortlist.csv"]:
        path = os.path.join(out_dir, f)
        if not os.path.exists(path): continue
        df = pd.read_csv(path)
        df["papers_with_abstract"] = df["paper_titles"].apply(
            lambda s: expand_brief(s, title_to_oneliner, title_to_url))
        df.to_csv(path, index=False, quoting=csv.QUOTE_ALL)
        print(f"  {f}: papers_with_abstract added")

    # 3) long + wide-papers for the actionable shortlist (and lean filtered)
    for base in [f"{conf}_shortlist", f"{conf}_filtered"]:
        wide_path = os.path.join(out_dir, base + ".csv")
        if not os.path.exists(wide_path): continue
        long_path = os.path.join(out_dir, base + "_long.csv")
        wp_path = os.path.join(out_dir, base + "_wide_papers.csv")
        make_long(wide_path, long_path, title_to_oneliner, title_to_url)
        make_wide_papers(long_path, wp_path)
        print(f"  {base}_long.csv + {base}_wide_papers.csv")


if __name__ == "__main__":
    main()

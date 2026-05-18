"""Final output shaping — produces a clean 3-file cascade for Sheets/CRM import.

  <conf>_all_authors.csv     superset of unique authors (~5k), with affiliation/country/
                              sector/email when known. Look here for unknown-country
                              candidates that didn't make the shortlist.
  <conf>_shortlist.csv        country-filtered + sector + seniority + h_index + email +
                              ROR + openalex_confidence. PRIMARY deliverable. Wide format,
                              papers joined in one cell.
  <conf>_shortlist_papers.csv same authors as shortlist, one row per author with explicit
                              paper_1_title / paper_1_url / paper_1_abstract through
                              paper_N_* columns. For CRM imports and mail-merge.

All CSVs are written with csv.QUOTE_ALL for clean Google Sheets import. Intermediate
artifacts (candidates / unique_authors / authors_arxiv / filtered_* / shortlist_long /
unknown_country) are removed at the end of this stage.
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


def build_all_authors(authors_arxiv_path: str, out_path: str,
                       title_to_oneliner: dict, title_to_url: dict):
    """Superset: every unique author, with affiliation/country/sector/email when known."""
    df = pd.read_csv(authors_arxiv_path)
    df["papers_with_abstract"] = df["paper_titles"].apply(
        lambda s: _expand_brief(s, title_to_oneliner, title_to_url))
    # Order columns sensibly
    preferred = ["author_name", "n_matched_papers", "matched_areas",
                 "country", "ror_country", "ror_sector",
                 "affiliation", "ror_name", "email",
                 "paper_titles", "papers_with_abstract", "paper_urls",
                 "linkedin_search", "ror_id", "ror_score"]
    cols = [c for c in preferred if c in df.columns] + \
           [c for c in df.columns if c not in preferred]
    df = df[cols]
    df.to_csv(out_path, index=False, quoting=csv.QUOTE_ALL)
    return df


def build_shortlist(shortlist_in_path: str, out_path: str,
                    title_to_oneliner: dict, title_to_url: dict):
    df = pd.read_csv(shortlist_in_path)
    df["papers_with_abstract"] = df["paper_titles"].apply(
        lambda s: _expand_brief(s, title_to_oneliner, title_to_url))
    preferred = ["author_name", "country", "sector", "seniority",
                 "n_matched_papers", "h_index", "works_count",
                 "openalex_confidence", "affiliation", "ror_name", "ror_country",
                 "email", "homepage", "matched_areas",
                 "paper_titles", "papers_with_abstract", "paper_urls",
                 "linkedin_search", "openalex_id", "ror_id", "ror_sector", "ror_score"]
    cols = [c for c in preferred if c in df.columns] + \
           [c for c in df.columns if c not in preferred]
    df = df[cols]
    df.to_csv(out_path, index=False, quoting=csv.QUOTE_ALL)
    return df


def build_shortlist_papers(shortlist_df: pd.DataFrame, out_path: str,
                            title_to_oneliner: dict, title_to_url: dict):
    """One row per author with explicit paper_N_title/url/abstract columns."""
    rows = []
    max_papers = 0
    for _, r in shortlist_df.iterrows():
        titles_str = r.get("paper_titles") or ""
        titles = [t.strip() for t in str(titles_str).split(" | ") if t.strip()]
        max_papers = max(max_papers, len(titles))
        base = r.drop(["paper_titles", "papers_with_abstract", "paper_urls"],
                      errors="ignore").to_dict()
        base["num_papers"] = len(titles)
        for i, t in enumerate(titles, start=1):
            base[f"paper_{i}_title"] = t
            base[f"paper_{i}_url"] = title_to_url.get(t, "")
            base[f"paper_{i}_abstract"] = title_to_oneliner.get(t, "")
        rows.append(base)
    out = pd.DataFrame(rows)
    # Reorder: static cols, num_papers, then paper_1_* ... paper_N_*
    static_cols = [c for c in out.columns if not c.startswith("paper_")
                   and c != "num_papers"]
    ordered = static_cols + ["num_papers"]
    for i in range(1, max_papers + 1):
        for k in ("title", "url", "abstract"):
            col = f"paper_{i}_{k}"
            if col in out.columns:
                ordered.append(col)
    out = out[ordered]
    out.to_csv(out_path, index=False, quoting=csv.QUOTE_ALL)


def _expand_brief(titles_str, title_to_oneliner, title_to_url):
    if pd.isna(titles_str) or not str(titles_str).strip():
        return ""
    titles = [t.strip() for t in str(titles_str).split(" | ") if t.strip()]
    out = []
    for t in titles:
        ol = title_to_oneliner.get(t, "")
        url = title_to_url.get(t, "")
        out.append(f"{t} — {ol} ({url})" if ol else f"{t} ({url})")
    return "\n".join(out)


def cleanup_intermediates(out_dir: str, conf: str):
    """Remove intermediate CSVs that aren't part of the 3-file cascade."""
    drop = [
        f"{conf}_candidates.csv",
        f"{conf}_unique_authors.csv",
        f"{conf}_authors_arxiv.csv",
        f"{conf}_authors_enriched.csv",     # legacy from old pipeline
        f"{conf}_filtered.csv",
        f"{conf}_filtered_long.csv",
        f"{conf}_filtered_wide_papers.csv",
        f"{conf}_shortlist_long.csv",
        f"{conf}_shortlist_wide_papers.csv",  # superseded by _shortlist_papers.csv
        f"{conf}_unknown_country.csv",
    ]
    for fname in drop:
        p = os.path.join(out_dir, fname)
        if os.path.exists(p):
            os.remove(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--keep-intermediates", action="store_true",
                    help="Don't delete the candidates/unique_authors/etc. files")
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    conf = cfg["conference"].lower() + str(cfg["year"])

    papers = json.load(open(os.path.join(out_dir, "papers_matched.json")))
    title_to_oneliner = {p["title"]: first_sentence(p.get("abstract","")) for p in papers}
    title_to_url = {p["title"]: p["url"] for p in papers}

    # Build all_authors from the post-ROR authors_arxiv.csv (superset, ~5k rows)
    aa_in = os.path.join(out_dir, f"{conf}_authors_arxiv.csv")
    all_out = os.path.join(out_dir, f"{conf}_all_authors.csv")
    all_df = build_all_authors(aa_in, all_out, title_to_oneliner, title_to_url)
    print(f"  {conf}_all_authors.csv: {len(all_df)} authors")

    # Build shortlist from the enriched shortlist (post-openalex, ~700 rows)
    sl_in = os.path.join(out_dir, f"{conf}_shortlist.csv")
    sl_df = build_shortlist(sl_in, sl_in, title_to_oneliner, title_to_url)
    print(f"  {conf}_shortlist.csv: {len(sl_df)} authors")

    # Build the wide-papers variant for CRM imports
    sp_out = os.path.join(out_dir, f"{conf}_shortlist_papers.csv")
    build_shortlist_papers(sl_df, sp_out, title_to_oneliner, title_to_url)
    print(f"  {conf}_shortlist_papers.csv: {len(sl_df)} authors")

    if not args.keep_intermediates:
        cleanup_intermediates(out_dir, conf)
        print(f"\n  cleaned up intermediate CSVs (use --keep-intermediates to retain)")


if __name__ == "__main__":
    main()

"""Bulk arxiv fetch + parallel PDF first-page parse to get per-author affiliations.

Steps:
  1. Build arxiv_index.json — paginate cs.CV/AI/LG/RO/GR/MM for the conference's preprint
     window. Cache on disk; reused across runs.
  2. Locally fuzzy-match each matched paper title against the arxiv index.
  3. Parallel PDF download + first-page text extraction (pdfminer).
  4. Parse author lines and numbered affiliations; map author position → affil index.
  5. Infer country code from affiliation string.
  6. Aggregate per author across their matched papers → cvpr2026_authors_arxiv.csv style.

Reads:  <output_dir>/papers_matched.json
Writes: <output_dir>/arxiv_index.json  (cached, reused)
        <output_dir>/pass_c_results.json  (per-paper parse, resumable)
        <output_dir>/<conf>_authors_arxiv.csv
        <output_dir>/<conf>_candidates.csv
        <output_dir>/<conf>_unique_authors.csv
"""
import argparse, json, os, re, time, tempfile, sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import requests
import pandas as pd

ARXIV_QUERY = "http://export.arxiv.org/api/query"

# Country detection: keyword → ISO 3166-1 alpha-2
COUNTRY_HINTS = {
    "United States":"US", "USA":"US", "U.S.":"US",
    "United Kingdom":"GB", "UK":"GB", "England":"GB", "Scotland":"GB",
    "Switzerland":"CH", "Germany":"DE", "France":"FR",
    "Netherlands":"NL", "Belgium":"BE", "Spain":"ES", "Italy":"IT",
    "Sweden":"SE", "Denmark":"DK", "Norway":"NO", "Finland":"FI",
    "Austria":"AT", "Poland":"PL", "Czech":"CZ", "Greece":"GR",
    "Ireland":"IE", "Portugal":"PT", "Israel":"IL",
    "Canada":"CA", "China":"CN", "India":"IN", "Japan":"JP",
    "Korea":"KR", "Singapore":"SG", "Australia":"AU", "Brazil":"BR",
    "Hong Kong":"HK", "Taiwan":"TW",
}
INSTITUTION_COUNTRY = {
    # US
    "MIT":"US","Stanford":"US","Berkeley":"US","Carnegie Mellon":"US","CMU":"US",
    "Harvard":"US","Princeton":"US","Caltech":"US","Cornell":"US","Yale":"US",
    "Columbia":"US","University of Texas":"US","UT Austin":"US","UCLA":"US","USC":"US",
    "UCSD":"US","University of Washington":"US","University of Illinois":"US","UIUC":"US",
    "Georgia Tech":"US","Johns Hopkins":"US","NYU":"US","Brown University":"US",
    "Google":"US","Meta":"US","NVIDIA":"US","Apple":"US","Microsoft":"US","Amazon":"US",
    "Adobe":"US","OpenAI":"US","Anthropic":"US","Salesforce":"US","IBM":"US",
    # UK
    "UCL":"GB","University College London":"GB","Oxford":"GB","Cambridge":"GB",
    "Imperial College":"GB","Edinburgh":"GB","DeepMind":"GB",
    # Europe
    "ETH":"CH","EPFL":"CH","TU Munich":"DE","TUM":"DE","Max Planck":"DE",
    "INRIA":"FR","University of Amsterdam":"NL","Delft":"NL","TU Delft":"NL",
    "KU Leuven":"BE","KTH":"SE","Chalmers":"SE",
    # CN/HK/TW/SG/KR/JP
    "Tsinghua":"CN","Peking University":"CN","PKU":"CN","Shanghai Jiao Tong":"CN",
    "SJTU":"CN","Zhejiang":"CN","Fudan":"CN","USTC":"CN","Sun Yat-sen":"CN",
    "Tencent":"CN","Bytedance":"CN","Alibaba":"CN","Huawei":"CN","Baidu":"CN","DAMO":"CN",
    "HKUST":"HK","HKU":"HK","CUHK":"HK",
    "NUS":"SG","NTU":"SG","KAIST":"KR","Seoul National":"KR","POSTECH":"KR",
    "Tokyo":"JP","Kyoto":"JP",
    # India
    "IIT":"IN","IISc":"IN","Indian Institute":"IN",
    # Canada / AU
    "Toronto":"CA","McGill":"CA","Waterloo":"CA","UBC":"CA","Mila":"CA","Vector Institute":"CA",
    "Sydney":"AU","Monash":"AU","ANU":"AU",
}


def make_session(mailto: str) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = f"conference-scout/0.1 (mailto:{mailto})"
    return s


def fuzzy(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    wa, wb = set(norm(a).split()), set(norm(b).split())
    if not wa or not wb: return 0
    return len(wa & wb) / max(len(wa), len(wb))


def fetch_window(session, cat, dfrom, dto, page_size, sleep_s):
    out = []
    start, fails = 0, 0
    while True:
        q = f"cat:{cat} AND submittedDate:[{dfrom} TO {dto}]"
        r = session.get(ARXIV_QUERY, params={
            "search_query": q, "start": start, "max_results": page_size,
            "sortBy": "submittedDate", "sortOrder": "descending",
        }, timeout=60)
        if r.status_code != 200:
            fails += 1
            print(f"  [{cat} {dfrom[:6]}-{dto[:6]}] start={start} status={r.status_code} (fail {fails}/3)")
            if fails >= 3:
                print(f"  → giving up past start={start}")
                break
            time.sleep(8); continue
        fails = 0
        entries = re.findall(r"<entry>([\s\S]*?)</entry>", r.text)
        if not entries: break
        for ent in entries:
            idm = re.search(r"<id>http://arxiv\.org/abs/([^<]+)</id>", ent)
            tm = re.search(r"<title>([\s\S]*?)</title>", ent, re.DOTALL)
            if idm and tm:
                out.append({"id": idm.group(1), "title": tm.group(1).strip()})
        print(f"  [{cat} {dfrom[:6]}-{dto[:6]}] fetched {start+len(entries)} (window: {len(out)})")
        if len(entries) < page_size: break
        start += page_size
        time.sleep(sleep_s)
    return out


def build_arxiv_index(session, cfg, cache_path):
    if os.path.exists(cache_path):
        cache = json.load(open(cache_path))
        print(f"  resuming arxiv index from {cache_path} ({len(cache)} papers)")
        return cache
    merged = {}
    for cat in cfg["arxiv"]["categories"]:
        print(f"\n  fetching {cat}…")
        for dfrom, dto in cfg["arxiv"]["date_windows"]:
            for paper in fetch_window(session, cat, dfrom, dto,
                                       cfg["arxiv"]["page_size"],
                                       cfg["arxiv"]["api_sleep_seconds"]):
                merged.setdefault(paper["id"], paper["title"])
            time.sleep(cfg["arxiv"]["api_sleep_seconds"])
    json.dump(merged, open(cache_path, "w"))
    print(f"  cached arxiv index: {len(merged)} unique papers")
    return merged


def match_titles(papers, arxiv_index, threshold):
    norm = lambda s: re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    arxiv_norm = {aid: norm(t) for aid, t in arxiv_index.items()}
    word_to_aids = defaultdict(set)
    for aid, n in arxiv_norm.items():
        for w in set(n.split()):
            if len(w) >= 4:
                word_to_aids[w].add(aid)
    matched = {}
    for p in papers:
        target = norm(p["title"])
        long_words = {w for w in target.split() if len(w) >= 4}
        cands = Counter()
        for w in long_words:
            for aid in word_to_aids.get(w, ()):
                cands[aid] += 1
        best_id, best_score = None, 0
        for aid, _ in cands.most_common(20):
            s = fuzzy(p["title"], arxiv_index[aid])
            if s > best_score:
                best_id, best_score = aid, s
        matched[p["paper_id"]] = best_id if best_score >= threshold else None
    return matched


def pdf_bytes_for(session, arxiv_id):
    """Download an arxiv PDF; return raw bytes or empty bytes on failure."""
    try:
        r = session.get(f"https://arxiv.org/pdf/{arxiv_id}", timeout=60)
        if r.status_code != 200 or len(r.content) < 1000:
            return b""
        return r.content
    except Exception:
        return b""


def pdf_first_page_text(pdf_bytes):
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        return ""
    if not pdf_bytes:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes); path = f.name
    try:
        return extract_text(path, maxpages=1) or ""
    except Exception:
        return ""
    finally:
        os.unlink(path)


# Back-compat shim — older callers still expect text from this name
def pdf_first_page(session, arxiv_id):
    return pdf_first_page_text(pdf_bytes_for(session, arxiv_id))


def country_of(affil: str) -> str:
    for word, code in COUNTRY_HINTS.items():
        if re.search(rf"\b{re.escape(word)}\b", affil, re.I): return code
    for kw, code in INSTITUTION_COUNTRY.items():
        if re.search(rf"\b{re.escape(kw)}\b", affil, re.I): return code
    return ""


AFFIL_KEYWORD = re.compile(
    r"(University|Institute|Laborator|Lab\b|College|School|Research|Inc\.?|Corp\b|"
    r"Ltd\b|GmbH|Polytechnic|Academia|Adobe|Google|Meta|NVIDIA|Apple|Microsoft|"
    r"Amazon|OpenAI|DeepMind|Anthropic|Tencent|Bytedance|Alibaba|Huawei|Baidu|"
    r"ETH|EPFL|INRIA|KAIST|HKUST|HKU|CUHK|NUS|NTU|MIT|CMU|Tsinghua|Peking|PKU|"
    r"SJTU|USTC|Zhejiang|Fudan|IBM|Salesforce|Disney|Sony|Samsung|Stanford|"
    r"Berkeley|Mila|DAMO|Vector|Toyota)", re.I)
AFFIL_LINE = re.compile(r"^\s*(\d{1,2})[\s\.\)]*\s*(.+?)\s*$")
AUTHOR_TOKEN = re.compile(
    r"([A-Z][A-Za-zÀ-ÿ\.\-']+(?:\s+[A-Z][A-Za-zÀ-ÿ\.\-']+){0,4})\s*([\d,†\*†‡§]*)")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def match_emails_to_authors(emails: list[str], authors: list[dict]) -> None:
    """Heuristically link first-page emails to parsed authors by local-part similarity.
    Mutates each author dict to add `email`. Local parts often match firstname.lastname,
    lastname, or initials — fuzzy match against the author's name tokens.
    """
    used = set()
    for au in authors:
        if au.get("email"): continue
        name = au["name"].lower()
        tokens = [t for t in re.split(r"[\s\.\-']", name) if len(t) >= 2]
        best, best_score = None, 0
        for em in emails:
            if em in used: continue
            local = em.split("@", 1)[0].lower()
            # Score: count tokens that appear in the local part as substrings
            score = sum(1 for t in tokens if t in local or local in t)
            # Bonus for last-name match (last token of the name)
            if tokens and tokens[-1] in local:
                score += 1
            if score > best_score:
                best, best_score = em, score
        if best and best_score >= 1:
            au["email"] = best
            used.add(best)


def parse_authors_and_affils(text: str):
    lines = text.splitlines()[:120]
    affils_by_num = {}
    first_affil_line = None
    for i, l in enumerate(lines):
        m = AFFIL_LINE.match(l)
        if not m: continue
        idx, body = int(m.group(1)), m.group(2).strip()
        if AFFIL_KEYWORD.search(body) and 4 < len(body) < 200 and \
                not body.lower().startswith(("figure","table","abstract")):
            affils_by_num.setdefault(idx, body)
            if first_affil_line is None: first_affil_line = i
    affils = [{"idx": i, "text": affils_by_num[i], "country": country_of(affils_by_num[i])}
              for i in sorted(affils_by_num.keys())]

    authors = []
    if affils_by_num:
        for l in lines[:first_affil_line or len(lines)]:
            if len(l.strip()) < 4 or len(l) > 250: continue
            if "abstract" in l.lower(): break
            for m in AUTHOR_TOKEN.finditer(l):
                name = m.group(1).strip(" ,")
                digits = [int(d) for d in re.findall(r"\d", m.group(2))]
                if len(name.split()) < 2: continue
                low = name.lower()
                if any(w in low for w in
                       ("abstract","figure","table","introduction","university",
                        "institute","research","the ","we ","our ")):
                    continue
                authors.append({"name": name, "aff_indices": digits})
    seen, deduped = set(), []
    for a in authors:
        k = a["name"].lower()
        if k in seen: continue
        seen.add(k); deduped.append(a)

    # Extract emails from first page text and link them to authors by local-part similarity
    emails = list(dict.fromkeys(EMAIL_PATTERN.findall(text)))  # dedupe preserving order
    if emails:
        match_emails_to_authors(emails, deduped)

    return deduped, affils


def parse_pdfs(matched, papers, session, cfg, results_path):
    paper_by_id = {p["paper_id"]: p for p in papers}
    state = json.load(open(results_path)) if os.path.exists(results_path) else {}
    todo = [(pid, aid) for pid, aid in matched.items() if aid and pid not in state]
    if not todo:
        return state
    print(f"  parsing {len(todo)} PDFs (workers={cfg['arxiv']['pdf_workers']})")

    # Optional GROBID — produces structurally cleaner author/affiliation extracts than
    # pdfminer + regex. Skill works without it (auto-fallback) but quality jumps when on.
    grobid_url = None
    grobid_cfg = cfg.get("grobid", {})
    if grobid_cfg.get("enabled"):
        try:
            from grobid_parse import is_grobid_alive, parse_pdf_with_grobid
            if is_grobid_alive(grobid_cfg.get("url", "http://localhost:8070")):
                grobid_url = grobid_cfg.get("url", "http://localhost:8070")
                print(f"  using GROBID at {grobid_url}")
            else:
                print(f"  GROBID configured but not reachable; falling back to pdfminer")
        except ImportError:
            pass

    def work(item):
        pid, aid = item
        pdf_bytes = pdf_bytes_for(session, aid)
        if not pdf_bytes:
            return pid, {"title": paper_by_id[pid]["title"], "arxiv_id": aid,
                         "affils": [], "authors": []}
        # Try GROBID first if available
        if grobid_url:
            from grobid_parse import parse_pdf_with_grobid
            authors, affils = parse_pdf_with_grobid(pdf_bytes, grobid_url)
            if authors or affils:
                return pid, {"title": paper_by_id[pid]["title"], "arxiv_id": aid,
                             "affils": affils, "authors": authors}
        # Fallback: pdfminer + regex
        text = pdf_first_page_text(pdf_bytes)
        if not text:
            return pid, {"title": paper_by_id[pid]["title"], "arxiv_id": aid,
                         "affils": [], "authors": []}
        authors, affils = parse_authors_and_affils(text)
        return pid, {"title": paper_by_id[pid]["title"], "arxiv_id": aid,
                     "affils": affils, "authors": authors}

    done = 0
    with ThreadPoolExecutor(max_workers=cfg["arxiv"]["pdf_workers"]) as pool:
        futs = {pool.submit(work, it): it for it in todo}
        for f in as_completed(futs):
            pid, res = f.result()
            state[pid] = res
            done += 1
            if done % 25 == 0:
                json.dump(state, open(results_path, "w"), ensure_ascii=False)
                n_aff = sum(1 for v in state.values() if v.get("affils"))
                print(f"    parsed {done}/{len(todo)} | with affils: {n_aff}")
    for pid, aid in matched.items():
        if pid not in state:
            state[pid] = {"title": paper_by_id[pid]["title"], "arxiv_id": None,
                          "affils": [], "authors": []}
    json.dump(state, open(results_path, "w"), ensure_ascii=False)
    return state


def aggregate(papers, state, cfg, out_dir):
    conf = cfg["conference"].lower() + str(cfg["year"])
    papers_by_id = {p["paper_id"]: p for p in papers}

    name_to_affils, name_to_countries = defaultdict(Counter), defaultdict(Counter)
    name_to_emails = defaultdict(Counter)
    for pid, rec in state.items():
        if not rec.get("affils"): continue
        paper = papers_by_id.get(pid)
        if not paper: continue
        pdf_authors = {a["name"].lower(): a for a in rec.get("authors", [])}
        all_affils = rec["affils"]
        for cvpr_name in paper["authors"]:
            pa = pdf_authors.get(cvpr_name.lower())
            if not pa:
                last = cvpr_name.split()[-1].lower()
                for k, v in pdf_authors.items():
                    if k.split()[-1] == last: pa = v; break
            affs = ([a for a in all_affils if a["idx"] in set(pa["aff_indices"])]
                    if pa and pa["aff_indices"] else all_affils)
            for a in affs:
                name_to_affils[cvpr_name][a["text"]] += 1
                if a["country"]: name_to_countries[cvpr_name][a["country"]] += 1
            if pa and pa.get("email"):
                name_to_emails[cvpr_name][pa["email"]] += 1

    # candidates.csv: one row per author×paper
    cand_rows = []
    for p in papers:
        for name in p["authors"]:
            cand_rows.append({
                "paper_title": p["title"],
                "matched_areas": ", ".join(p["matched_areas"]),
                "author_name": name,
                "paper_url": p["url"],
                "linkedin_search": f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(name)}",
            })
    pd.DataFrame(cand_rows).to_csv(os.path.join(out_dir, f"{conf}_candidates.csv"), index=False)

    # unique_authors.csv: one row per author with all paper titles joined
    df = pd.DataFrame(cand_rows)
    agg = df.groupby("author_name").agg(
        n_matched_papers=("paper_title", "nunique"),
        matched_areas=("matched_areas", lambda s: ", ".join(sorted({a.strip()
            for row in s for a in row.split(",") if a.strip()}))),
        paper_titles=("paper_title", lambda s: " | ".join(sorted(set(s)))),
        paper_urls=("paper_url", lambda s: " | ".join(sorted(set(s)))),
        linkedin_search=("linkedin_search", "first"),
    ).reset_index().sort_values("n_matched_papers", ascending=False)
    agg.to_csv(os.path.join(out_dir, f"{conf}_unique_authors.csv"), index=False)

    # authors_arxiv.csv: unique + affiliation + country + email
    rows = []
    for _, row in agg.iterrows():
        name = row["author_name"]
        affs = name_to_affils.get(name, Counter())
        ctrys = name_to_countries.get(name, Counter())
        emails = name_to_emails.get(name, Counter())
        rows.append({**row.to_dict(),
                     "affiliation": affs.most_common(1)[0][0] if affs else "",
                     "country": ctrys.most_common(1)[0][0] if ctrys else "",
                     "email": emails.most_common(1)[0][0] if emails else ""})
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(out_dir, f"{conf}_authors_arxiv.csv"), index=False)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    mailto = cfg.get("openalex", {}).get("mailto", "you@example.com")

    session = make_session(mailto)
    papers = json.load(open(os.path.join(out_dir, "papers_matched.json")))
    print(f"[enrich_arxiv] {len(papers)} matched papers")

    print("\n[enrich_arxiv] step 1: build arxiv bulk index")
    arxiv_index = build_arxiv_index(session, cfg,
                                    os.path.join(out_dir, "arxiv_index.json"))

    print(f"\n[enrich_arxiv] step 2: match {len(papers)} titles → {len(arxiv_index)} arxiv papers")
    matched = match_titles(papers, arxiv_index, cfg["arxiv"]["fuzzy_match_threshold"])
    n_match = sum(1 for v in matched.values() if v)
    print(f"  matched: {n_match}/{len(papers)} ({n_match/max(1,len(papers))*100:.0f}%)")

    print("\n[enrich_arxiv] step 3: PDF parse (parallel)")
    state = parse_pdfs(matched, papers, session, cfg,
                       os.path.join(out_dir, "pass_c_results.json"))
    n_aff = sum(1 for v in state.values() if v.get("affils"))
    print(f"  papers with parsed affils: {n_aff}")

    print("\n[enrich_arxiv] step 4: aggregate per author")
    out = aggregate(papers, state, cfg, out_dir)
    print(f"  saved {len(out)} authors → {cfg['conference'].lower()+str(cfg['year'])}_authors_arxiv.csv")
    print(f"  with affiliation: {(out.affiliation != '').sum()}")
    print(f"  with country:     {(out.country != '').sum()}")
    print("  top countries:")
    print(out[out.country != ""]["country"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()

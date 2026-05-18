"""Scrape camera-ready PDFs from CVF Open Access (openaccess.thecvf.com).

CVF posts every accepted main-conference paper as a PDF here after the conference
(typically 1–2 weeks before the event for CVPR/ICCV). URL pattern:

  https://openaccess.thecvf.com/content/CVPR2024/papers/<title-slug>_<paper_id>_CVPR_2024_paper.pdf

This is the only source that covers 100% of accepted papers — closes the ~30% gap left
by arxiv (some accepted papers have no preprint at all).

Use after `scrape_cvf` has populated papers_raw.json. This script walks the openaccess
index page, downloads PDFs, runs GROBID (preferred) or pdfminer to extract authors +
affiliations + emails, and merges the result into pass_c_results.json so the downstream
stages pick up the extra coverage transparently.

Reads:  <output_dir>/papers_raw.json
Writes: <output_dir>/openaccess_pdfs/             (cached PDFs)
        <output_dir>/pass_c_results.json          (merged with arxiv-derived data)
"""
import argparse, json, os, re, time, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

from enrich_arxiv import parse_authors_and_affils, pdf_first_page_text


def make_session():
    s = requests.Session()
    s.headers["User-Agent"] = "conference-scout/0.1"
    return s


def index_url_for(conf: str, year: int) -> str:
    return f"https://openaccess.thecvf.com/{conf}{year}"


def discover_paper_urls(session, index_url: str) -> list[str]:
    """Walk the CVF Open Access index and return all paper PDF URLs."""
    r = session.get(index_url, timeout=30)
    if r.status_code != 200:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    pdfs = []
    for a in soup.find_all("a", href=re.compile(r"\.pdf$", re.I)):
        href = a["href"]
        if "/papers/" in href and "supplemental" not in href.lower():
            full = href if href.startswith("http") else f"https://openaccess.thecvf.com/{href.lstrip('/')}"
            pdfs.append(full)
    return sorted(set(pdfs))


def slug_to_title(url: str) -> str:
    """Recover an approximate title from the URL slug for matching against papers_raw."""
    fname = url.rsplit("/", 1)[-1]
    # e.g. "Smith_Cool_Method_CVPR_2024_paper.pdf"
    stem = re.sub(r"_(?:CVPR|ICCV|ECCV|WACV)_\d{4}_paper\.pdf$", "", fname, flags=re.I)
    # Drop leading "Lastname_" of the first author
    parts = stem.split("_", 1)
    title = parts[1] if len(parts) > 1 else parts[0]
    return title.replace("_", " ")


def match_to_paper(papers: list[dict], slug_title: str) -> dict | None:
    norm = lambda s: re.sub(r"[^a-z0-9 ]", " ", s.lower())
    tn = set(norm(slug_title).split())
    if not tn: return None
    best, best_score = None, 0
    for p in papers:
        pn = set(norm(p["title"]).split())
        if not pn: continue
        overlap = len(tn & pn) / max(len(tn), len(pn))
        if overlap > best_score:
            best, best_score = p, overlap
    return best if best_score >= 0.6 else None


def parse_pdf(session, pdf_url: str, grobid_url: str | None) -> tuple[list, list]:
    try:
        r = session.get(pdf_url, timeout=60)
        if r.status_code != 200 or len(r.content) < 1000: return [], []
        if grobid_url:
            from grobid_parse import parse_pdf_with_grobid
            authors, affils = parse_pdf_with_grobid(r.content, grobid_url)
            if authors or affils:
                return authors, affils
        # Fallback to pdfminer + regex
        text = pdf_first_page_text(r.content)
        if not text: return [], []
        return parse_authors_and_affils(text)
    except Exception:
        return [], []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    conf = cfg["conference"]
    year = cfg["year"]

    papers = json.load(open(os.path.join(out_dir, "papers_raw.json")))
    print(f"[cvf_openaccess] {len(papers)} known papers")

    session = make_session()
    grobid_url = (cfg.get("grobid", {}) or {}).get("url") if (cfg.get("grobid", {}) or {}).get("enabled") else None
    if grobid_url:
        from grobid_parse import is_grobid_alive
        if not is_grobid_alive(grobid_url):
            grobid_url = None
            print("  GROBID not reachable; using pdfminer fallback")

    index_url = index_url_for(conf, year)
    print(f"  discovering PDFs at {index_url}")
    pdf_urls = discover_paper_urls(session, index_url)
    if not pdf_urls:
        print(f"  no PDFs found — index page may not be live yet "
              f"(CVF publishes proceedings around the conference date)")
        return
    print(f"  found {len(pdf_urls)} PDFs")

    # Load existing parse state to merge into
    state_path = os.path.join(out_dir, "pass_c_results.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}

    # Resolve each PDF URL → paper_id via slug-title fuzzy match
    todo = []
    for url in pdf_urls:
        slug_t = slug_to_title(url)
        p = match_to_paper(papers, slug_t)
        if not p: continue
        # Skip if we already have affiliations from arxiv
        if state.get(p["paper_id"], {}).get("affils"): continue
        todo.append((p["paper_id"], url, p["title"]))

    print(f"  to scrape: {len(todo)} (skipping papers already enriched via arxiv)")

    def work(item):
        pid, url, title = item
        authors, affils = parse_pdf(session, url, grobid_url)
        return pid, title, url, authors, affils

    workers = cfg.get("arxiv", {}).get("pdf_workers", 12)
    done, n_filled = 0, 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(work, t): t for t in todo}
        for f in as_completed(futs):
            pid, title, url, authors, affils = f.result()
            state[pid] = {"title": title, "openaccess_url": url,
                          "affils": affils, "authors": authors}
            if affils: n_filled += 1
            done += 1
            if done % 25 == 0:
                json.dump(state, open(state_path, "w"), ensure_ascii=False)
                print(f"    {done}/{len(todo)} | with affils: {n_filled}")

    json.dump(state, open(state_path, "w"), ensure_ascii=False)
    print(f"\n  added affiliations for {n_filled} papers from CVF Open Access")
    print(f"  re-run enrich_arxiv (skip to aggregate stage) to rebuild author-level CSVs")


if __name__ == "__main__":
    main()

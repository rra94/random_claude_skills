"""Scrape a CVF virtual conference site (CVPR / ICCV / ECCV / WACV).

Reads cvf_url from config, walks the papers.html index, fetches each poster page
in parallel, extracts title + authors + abstract.

Output: <output_dir>/papers_raw.json — list of {paper_id, title, url, authors, abstract}.
"""
import argparse, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup


def get_all_paper_urls(index_url: str) -> list[dict]:
    base = re.match(r"(https?://[^/]+)", index_url).group(1)
    r = requests.get(index_url, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    seen, papers = set(), []
    for a in soup.find_all("a", href=re.compile(r"/virtual/\d{4}/poster/\d+")):
        href = a["href"]
        if href in seen: continue
        seen.add(href)
        papers.append({
            "paper_id": href.split("/")[-1],
            "title": a.get_text(strip=True),
            "url": base + href,
        })
    return papers


def fetch_paper_details(paper: dict) -> dict:
    try:
        r = requests.get(paper["url"], timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        # Authors: line containing ⋅ (CVF middle-dot separator)
        authors = []
        for line in soup.get_text(separator="\n").split("\n"):
            if "⋅" in line:
                authors = [a.strip() for a in line.split("⋅") if a.strip()]
                break
        if not authors:
            sub = soup.find(class_=re.compile("author"))
            if sub:
                txt = sub.get_text(strip=True)
                authors = [a.strip() for a in re.split(r"[⋅,;]", txt) if a.strip()]
        # Abstract: <div class="abstract-content">
        ac = soup.find("div", class_="abstract-content")
        abstract = ac.get_text(" ", strip=True)[:2000] if ac else ""
        paper["authors"] = authors
        paper["abstract"] = abstract
    except Exception as e:
        paper.setdefault("authors", [])
        paper.setdefault("abstract", "")
        print(f"  [warn] {paper['paper_id']}: {e}", file=sys.stderr)
    return paper


def fetch_all_details(papers: list[dict], max_workers: int = 16) -> list[dict]:
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_paper_details, p): p for p in papers}
        for i, f in enumerate(as_completed(futures)):
            results.append(f.result())
            if (i + 1) % 200 == 0:
                print(f"  fetched {i+1}/{len(papers)}")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))

    cvf_url = cfg["scrape"]["cvf_url"]
    max_workers = cfg["scrape"].get("max_workers", 16)
    out_dir = cfg["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    print(f"[scrape_cvf] indexing {cvf_url}")
    papers = get_all_paper_urls(cvf_url)
    print(f"  found {len(papers)} paper links")

    print(f"[scrape_cvf] fetching details (workers={max_workers})")
    papers = fetch_all_details(papers, max_workers=max_workers)
    print(f"  done: {len(papers)} papers")

    out_path = os.path.join(out_dir, "papers_raw.json")
    with open(out_path, "w") as f:
        json.dump(papers, f, ensure_ascii=False)
    print(f"  saved → {out_path}")


if __name__ == "__main__":
    main()

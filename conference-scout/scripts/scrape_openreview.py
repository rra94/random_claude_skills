"""Scrape an OpenReview-hosted venue (ICLR / NeurIPS / ICML / COLM / TMLR).

Reads openreview_venue_id from config (e.g. "ICLR.cc/2026/Conference") and uses
the OpenReview API v2 to fetch all accepted submissions.

Output: <output_dir>/papers_raw.json with the same shape as scrape_cvf.py.

Requires: pip install openreview-py
"""
import argparse, json, os, sys

try:
    import openreview
except ImportError:
    print("openreview-py not installed; run: pip install openreview-py", file=sys.stderr)
    sys.exit(1)


def fetch_accepted_papers(venue_id: str) -> list[dict]:
    """Return accepted papers under venue_id."""
    client = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")

    # Try standard submission invitation first
    submissions = client.get_all_notes(
        invitation=f"{venue_id}/-/Submission",
        details="replies",
    )
    if not submissions:
        # Fallback: filter by venueid metadata
        submissions = client.get_all_notes(content={"venueid": venue_id})

    papers = []
    for sub in submissions:
        c = sub.content
        # Accept only papers whose venueid matches (filters out withdrawn/rejected)
        venueid = c.get("venueid", {}).get("value", "")
        if venue_id not in venueid:
            continue
        papers.append({
            "paper_id": sub.id,
            "title": c.get("title", {}).get("value", ""),
            "url": f"https://openreview.net/forum?id={sub.id}",
            "authors": c.get("authors", {}).get("value", []),
            "authorids": c.get("authorids", {}).get("value", []),
            "abstract": c.get("abstract", {}).get("value", ""),
            "keywords": c.get("keywords", {}).get("value", []),
        })
    return papers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))

    venue_id = cfg["scrape"]["openreview_venue_id"]
    if not venue_id:
        print("config.scrape.openreview_venue_id is required", file=sys.stderr)
        sys.exit(1)

    out_dir = cfg["output_dir"]
    os.makedirs(out_dir, exist_ok=True)

    print(f"[scrape_openreview] fetching venue: {venue_id}")
    papers = fetch_accepted_papers(venue_id)
    print(f"  fetched {len(papers)} accepted papers")

    if not papers:
        print("  NOTE: 0 papers. Confirm venue uses OpenReview for the track you want.")
        print("  CVPR/ICCV main tracks do NOT use OpenReview — use scrape_cvf instead.")

    out_path = os.path.join(out_dir, "papers_raw.json")
    with open(out_path, "w") as f:
        json.dump(papers, f, ensure_ascii=False)
    print(f"  saved → {out_path}")


if __name__ == "__main__":
    main()

"""Classify scraped papers into target research areas via regex patterns.

Reads <output_dir>/papers_raw.json and config.classify.target_areas, writes
<output_dir>/papers_matched.json with one entry per paper that matched ≥1 area.
A paper matches an area if any of its regex patterns hits title+abstract.
"""
import argparse, json, os, re


def compile_patterns(target_areas: dict) -> dict:
    return {area: [re.compile(p, re.I) for p in pats]
            for area, pats in target_areas.items()}


def classify(papers: list[dict], compiled: dict) -> list[dict]:
    matched = []
    for p in papers:
        haystack = f"{p.get('title','')}\n{p.get('abstract','')}"
        areas = [a for a, pats in compiled.items()
                 if any(r.search(haystack) for r in pats)]
        if areas:
            p["matched_areas"] = areas
            matched.append(p)
    return matched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))

    out_dir = cfg["output_dir"]
    papers = json.load(open(os.path.join(out_dir, "papers_raw.json")))
    compiled = compile_patterns(cfg["classify"]["target_areas"])

    print(f"[classify] {len(papers)} input papers, {len(compiled)} target areas")
    matched = classify(papers, compiled)
    print(f"  matched: {len(matched)}")

    out_path = os.path.join(out_dir, "papers_matched.json")
    with open(out_path, "w") as f:
        json.dump(matched, f, ensure_ascii=False)
    print(f"  saved → {out_path}")

    # Per-area counts
    counts = {a: 0 for a in cfg["classify"]["target_areas"]}
    for p in matched:
        for a in p["matched_areas"]:
            counts[a] += 1
    print("\n  area breakdown:")
    for a, n in sorted(counts.items(), key=lambda x: -x[1]):
        if n: print(f"    {a:30s} {n}")


if __name__ == "__main__":
    main()

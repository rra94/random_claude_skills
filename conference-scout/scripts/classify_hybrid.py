"""Hybrid classifier — regex for recall, Claude for precision filtering.

Pipeline:
  1. Run the regex classifier (same as classify.py) → broad candidate set
  2. For each candidate, ask Claude whether it actually matches each tagged area
     (in batches of 20 to amortize cost)
  3. Drop papers Claude rejects; keep tagged areas Claude confirms

Cost on a 4,000-paper conference with ~1,000 regex candidates ≈ $1–2 with
claude-sonnet-4-6. Runtime ~3–5 min.

Reads:  <output_dir>/papers_raw.json
        config.classify.target_areas
Writes: <output_dir>/papers_matched.json   (precision-filtered)

Requires: pip install anthropic
Env: ANTHROPIC_API_KEY=sk-ant-...
"""
import argparse, json, os, re, sys, time

try:
    import anthropic
except ImportError:
    print("anthropic not installed; run: pip install anthropic", file=sys.stderr)
    sys.exit(1)


def compile_patterns(target_areas: dict):
    return {area: [re.compile(p, re.I) for p in pats]
            for area, pats in target_areas.items()}


def regex_classify(papers, compiled):
    matched = []
    for p in papers:
        haystack = f"{p.get('title','')}\n{p.get('abstract','')}"
        areas = [a for a, pats in compiled.items()
                 if any(r.search(haystack) for r in pats)]
        if areas:
            p["matched_areas"] = areas
            matched.append(p)
    return matched


def claude_filter(papers: list[dict], areas: list[str], batch_size: int = 20,
                  model: str = "claude-sonnet-4-6") -> list[dict]:
    """Ask Claude to confirm/reject the regex-assigned areas for each paper.
    Returns papers with `matched_areas` updated to Claude's verdict (or removed if empty)."""
    client = anthropic.Anthropic()
    areas_str = "\n".join(f"- {a}" for a in areas)
    refined = []

    for i in range(0, len(papers), batch_size):
        batch = papers[i:i+batch_size]
        prompt_papers = json.dumps([
            {"id": p["paper_id"], "title": p["title"],
             "abstract": (p.get("abstract") or "")[:500],
             "regex_areas": p["matched_areas"]}
            for p in batch
        ], indent=2)

        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": (
                f"For each paper, return ONLY the areas (from the regex-suggested list) "
                f"that genuinely describe the paper's contribution. Drop areas that were "
                f"matched on a tangential keyword (e.g. paper mentions 'robotics' but is "
                f"not a robotics paper). Return ONLY a JSON array: "
                f"[{{\"id\":\"...\", \"areas\":[\"...\"]}}].\n\n"
                f"Valid areas:\n{areas_str}\n\n"
                f"Papers:\n{prompt_papers}"
            )}],
        )
        text = resp.content[0].text.strip()
        text = text.removeprefix("```json").removesuffix("```").strip()
        try:
            results = {r["id"]: r["areas"] for r in json.loads(text)}
        except Exception:
            print(f"  [warn] couldn't parse Claude response for batch {i//batch_size}", file=sys.stderr)
            continue
        for p in batch:
            confirmed = [a for a in results.get(p["paper_id"], []) if a in areas]
            if confirmed:
                p["matched_areas"] = confirmed
                refined.append(p)
        if (i // batch_size) % 5 == 0:
            print(f"  {min(i+batch_size, len(papers))}/{len(papers)} | confirmed: {len(refined)}")
        time.sleep(0.3)

    return refined


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--model", default="claude-sonnet-4-6")
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]

    papers = json.load(open(os.path.join(out_dir, "papers_raw.json")))
    compiled = compile_patterns(cfg["classify"]["target_areas"])
    areas = list(cfg["classify"]["target_areas"].keys())

    print(f"[classify_hybrid] {len(papers)} input papers")
    print(f"  step 1: regex recall pass")
    candidates = regex_classify(papers, compiled)
    print(f"    {len(candidates)} regex candidates")

    print(f"  step 2: Claude precision filter ({args.model})")
    refined = claude_filter(candidates, areas, model=args.model)
    print(f"    {len(refined)} confirmed matches ({len(candidates)-len(refined)} rejected)")

    json.dump(refined, open(os.path.join(out_dir, "papers_matched.json"), "w"),
              ensure_ascii=False)
    print(f"  saved → papers_matched.json")


if __name__ == "__main__":
    main()

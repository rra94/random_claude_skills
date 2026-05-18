# Swapping in Claude for higher-precision classification

The default classifier is regex/keyword. It's fast and key-free but misses topics phrased
outside the keyword list. For higher-stakes hiring runs you can substitute Anthropic API
calls.

## When it's worth it

- You ran the default pipeline, browsed the shortlist, and noticed obvious off-topic papers
  (e.g. matched on "robot" because the paper mentioned "robotics-inspired regularization")
- You can name 5+ papers from the conference in your target area that the regex classifier
  missed entirely
- You're building a long-term, repeatable funnel and an extra ~$2/run is fine
- The conference has unusually noisy abstracts (e.g. workshop papers, tutorial summaries)

## Cost estimate

For a typical conference (~4,000 papers, ~500-char abstracts):
- Batch size: 20 papers per prompt
- ~200 API calls × ~5k input tokens + 1k output tokens = $1.50–$3 with Sonnet 4.6
- Runtime: ~5 min with light rate limiting

## Drop-in replacement: `classify_llm.py`

(Not bundled — recipe below. Save as `scripts/classify_llm.py`.)

```python
import argparse, json, os, time
import anthropic, pandas as pd

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]

    papers = json.load(open(os.path.join(out_dir, "papers_raw.json")))
    areas = list(cfg["classify"]["target_areas"].keys())
    areas_str = "\n".join(f"- {a}" for a in areas)

    client = anthropic.Anthropic()  # needs ANTHROPIC_API_KEY env var
    matched = []
    batch_size = 20

    for i in range(0, len(papers), batch_size):
        batch = papers[i:i+batch_size]
        batch_input = json.dumps([
            {"id": p["paper_id"], "title": p["title"],
             "abstract": p["abstract"][:500]}
            for p in batch
        ], indent=2)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": (
                f"Classify each paper into ONE OR MORE of these areas, or 'Other' if none fit. "
                f"Return ONLY a JSON array: [{{\"id\":\"...\",\"areas\":[...]}}].\n\n"
                f"Areas:\n{areas_str}\n\nPapers:\n{batch_input}"
            )}],
        )
        text = resp.content[0].text.strip().removeprefix("```json").removesuffix("```").strip()
        results = {r["id"]: r["areas"] for r in json.loads(text)}
        for p in batch:
            a = results.get(p["paper_id"], ["Other"])
            if a != ["Other"]:
                p["matched_areas"] = a
                matched.append(p)
        if (i//batch_size) % 5 == 0:
            print(f"  {min(i+batch_size, len(papers))}/{len(papers)}")
        time.sleep(0.5)

    json.dump(matched, open(os.path.join(out_dir, "papers_matched.json"), "w"),
              ensure_ascii=False)
    print(f"saved {len(matched)} matched papers")

if __name__ == "__main__":
    main()
```

## How to use

1. `pip install anthropic`
2. `export ANTHROPIC_API_KEY=sk-ant-...`
3. Replace the `classify` stage:
   ```bash
   python3 scripts/classify_llm.py --config my.json   # in place of classify.py
   python3 scripts/pipeline.py --config my.json --skip scrape,classify
   ```

## Hybrid approach

For best of both: run regex classify first (cheap, broad recall), then run LLM classify on
the matched subset to refine and re-tag with finer-grained areas. The LLM only sees ~1,000
papers instead of all 4,000, cutting cost ~4×.

# Semantic Scholar — seniority enrichment alternative to OpenAlex

Use this when OpenAlex's daily budget is the binding constraint (which it is on
conference-sized runs as of 2026 — see `known_limitations.md`).

## Why this exists

OpenAlex moved to a paid-credit model in 2026. The polite-pool free tier is $1/day, which
buys roughly 800 author lookups before requests return:

```
HTTP 429
{"error":"Rate limit exceeded","message":"Insufficient budget. This request costs $0.001
but you only have $0 remaining. Resets at midnight UTC."}
```

Conference shortlists typically have 700-2000 unique authors needing seniority enrichment,
so default OpenAlex exhausts mid-run and leaves most rows with empty h_index / works_count.

Semantic Scholar Graph API has a free tier that's much more forgiving:
- **With a free API key:** ~100 requests/sec, no daily cap mentioned
- **Without a key:** 1 req/sec, still completes a typical conference run in ~15 min

Both tiers populate the same downstream columns (h_index, works_count, seniority, sector,
homepage, openalex_confidence — column name kept for back-compat; `openalex_id` field
holds the S2 author URL).

## Get a key

1. Sign up at <https://www.semanticscholar.org/product/api>
2. Request an API key (instant for personal use; description like "researcher hiring
   pipeline" works)
3. Paste into your config:

   ```json
   "s2": {
     "api_key": "your-key-here",
     "sleep_seconds": 0.05
   }
   ```

   Or set the env var `S2_API_KEY=...` — the script picks it up automatically.

## Run

Drop-in replacement for the `enrich_openalex` stage:

```bash
# Instead of:
python3 scripts/enrich_openalex.py --config my.json

# Run:
python3 scripts/enrich_s2.py --config my.json
```

Outputs land in the same `<conf>_shortlist.csv` with the same columns, so `format_output`
and any downstream tooling work unchanged.

## Coverage differences vs OpenAlex

S2 disambiguation is slightly different from OpenAlex:
- Both struggle with common Chinese/Korean romanized names (the `openalex_confidence`
  column flags `low` for those — same semantics)
- S2 generally has BETTER coverage of CS/ML papers (it's CS-focused) but worse coverage
  of cross-disciplinary work
- S2 author profiles are more often linked to homepages (`homepage` column) than OpenAlex's
  (which is empty ~95% of the time)

## When to fall back to OpenAlex

If S2 misses authors that OpenAlex would have caught (rare for CV/ML researchers), you can
run both and merge — keep the row with the higher confidence label. The merge is left as
an exercise.

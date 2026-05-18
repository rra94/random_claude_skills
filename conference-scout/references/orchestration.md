# Running stages independently

The `pipeline.py` orchestrator runs every stage in order, but each stage can also run
standalone — useful when a downstream stage fails or you want to iterate on classification
patterns without re-scraping.

## Stage list

| Stage | Script | Inputs | Outputs |
|---|---|---|---|
| `scrape` | `scrape_cvf.py` or `scrape_openreview.py` | (web) | `papers_raw.json` |
| `classify` | `classify.py` | `papers_raw.json`, `config.classify` | `papers_matched.json` |
| `enrich_arxiv` | `enrich_arxiv.py` | `papers_matched.json` | `arxiv_index.json`, `pass_c_results.json`, `<conf>_candidates.csv`, `<conf>_unique_authors.csv`, `<conf>_authors_arxiv.csv` |
| `ror_resolve` | `ror_resolve.py` | `<conf>_authors_arxiv.csv` | adds `ror_id` / `ror_name` / `ror_country` / `ror_sector` / `ror_score` columns; overwrites `country` when ROR hits |
| `filter` | `filter_countries.py` | `<conf>_authors_arxiv.csv`, `config.filter` | `<conf>_filtered.csv`, `<conf>_unknown_country.csv` |
| `enrich_openalex` | `enrich_openalex.py` | `<conf>_filtered.csv` | `<conf>_shortlist.csv` |
| `format` | `format_output.py` | all of the above | adds abstract columns; produces `_long.csv` and `_wide_papers.csv` |

## Pipeline runner flags

```bash
# Full run
python3 scripts/pipeline.py --config my.json

# Skip stages you've already run
python3 scripts/pipeline.py --config my.json --skip scrape,classify

# Run a single stage
python3 scripts/pipeline.py --config my.json --only enrich_openalex
```

## Idempotency / resume behavior

- **`scrape`** overwrites `papers_raw.json` every run. Re-run if the conference site
  updated (new papers added between virtual platform launch and conference date).
- **`classify`** is cheap; just rerun whenever you edit `target_areas` patterns.
- **`enrich_arxiv`** caches:
  - `arxiv_index.json` — reused across runs. Delete to rebuild (~10–15 min)
  - `pass_c_results.json` — per-paper parse cache. Re-run safely; only unprocessed papers
    get downloaded
- **`ror_resolve`** caches `ror_cache.json` per unique affiliation string. Warm runs are
  near-instant; cold runs add ~3–5 min per 1k unique affiliations.
- **`filter`** is cheap; rerun whenever you change `keep_countries`
- **`enrich_openalex`** does NOT cache — re-running queries OpenAlex again for each author
  (~2 min for 600 authors)
- **`format`** is fast (<10 seconds); always safe to rerun

## Common iteration loop

After a full run, the most common reasons to re-run only some stages:

| Issue | Stages to re-run |
|---|---|
| Want to add/change target areas | `classify`, `enrich_arxiv`, `ror_resolve`, `filter`, `enrich_openalex`, `format` |
| Want to change country keep-list | `filter`, `enrich_openalex`, `format` |
| Want to refresh ROR-derived country/sector | `ror_resolve` (delete `ror_cache.json` first to force re-resolve), `filter`, `enrich_openalex`, `format` |
| Re-scraped the conference site for fresh papers | everything |
| Just want to fix CSV formatting | `format` only |
| Brave API key added for Phase D | `phase_d_homepage.py` separately, then `format` |

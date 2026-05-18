# ROR resolution strategy

The Research Organization Registry (<https://ror.org>) is a free public registry of
research institutions worldwide — universities, companies, government labs, hospitals,
nonprofits. Each org has a stable ROR ID, official name + aliases, country, GeoNames
location, type tags, domains, and cross-references to GRID / ISNI / Wikidata.

The `ror_resolve` stage takes the messy affiliation strings extracted from PDF first
pages and queries ROR's `/v2/organizations?affiliation=…` endpoint, which runs a
fuzzy matcher and returns the most likely org with a confidence score.

## What ROR fixes vs the hand-curated regex tables

| Signal | Regex table approach (legacy) | ROR approach |
|---|---|---|
| Country code | Hand-curated keyword list of ~50 country/institution mappings | ~120k organizations indexed; matches dirty affiliation strings like "Dept. of CS, Peking Univ., Beijing" |
| Sector (academic/industry) | Regex over ~100 company/university keywords | ROR `organization.types` ∈ {education, company, facility, government, healthcare, nonprofit, archive, other} |
| Authoritative institution name | First substring of the affiliation | `names[*]` with `ror_display` flag — canonical English name |
| Stable identifier across runs | None | ROR ID (e.g. `https://ror.org/02v51f717`) |

## Confidence threshold

The stage rejects matches below `score >= 0.7` (configurable via `MIN_SCORE`). At ≥0.7,
ROR has very high precision; below that, false positives kick in (especially for acronyms).
Affiliations that don't clear the threshold keep their regex-derived country values.

## Caching

ROR lookups are cached in `<output_dir>/ror_cache.json` keyed by exact affiliation string.
This matters because the same institution appears in dozens of papers — without caching
each unique string would be queried hundreds of times.

The cache persists across runs; deleting it forces a re-resolve (useful after ROR adds
new institutions or fixes an entry).

## Rate limits

ROR's anonymous limit is ~2,000 requests per 5 minutes. The default 0.1 s sleep keeps
the pipeline well under that for typical conference-sized inputs (~2,000 unique
affiliations from a 4,000-paper venue). For larger runs, raise `config.ror.sleep_seconds`
to 0.3.

## Known ROR misses

ROR struggles with:
- **Pure acronyms** that don't appear in the org's official aliases ("NTU 3SYSU 4NUS"
  doesn't match; the parser would need to split on digits and lookup each acronym
  separately — not currently done)
- **Multi-affiliation strings** (the first listed institution wins; secondary affiliations
  are dropped)
- **Multi-national companies** — querying "Microsoft" returns the German Microsoft
  branch (a separate ROR record) before US Microsoft. For these, the regex fallback
  often gives the more useful country answer (e.g. "Microsoft" → US in the regex table)

## When to skip the ROR stage

Add `ror_resolve` to `--skip` if:
- You're offline / on a flaky network (ROR adds ~3-5 minutes per ~1k unique affiliations)
- You're iterating on classification or filtering and don't want to re-query ROR each time
  (just keep the cache file and ROR is fast on warm runs)
- You're processing a non-research domain where ROR coverage is poor

## Output columns

After `ror_resolve` runs, `<conf>_authors_arxiv.csv` gains:

| Column | Meaning |
|---|---|
| `ror_id` | Stable ROR ID URL, e.g. `https://ror.org/02v51f717` |
| `ror_name` | Authoritative institution name |
| `ror_country` | ISO 3166-1 alpha-2 code |
| `ror_sector` | academic / industry / government / nonprofit / healthcare / other |
| `ror_score` | Match confidence (0.7–1.0 since we threshold) |

The legacy `country` column is overwritten with `ror_country` when ROR returned a hit,
otherwise it keeps the regex-derived value. The legacy `affiliation` column is left as-is
(raw parsed string) — use `ror_name` if you want the canonical institution name.

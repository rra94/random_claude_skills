# conference-scout

End-to-end Claude Code skill that builds a recruiter-grade shortlist of researchers from a
major ML/CV conference — filtered by topic and country, enriched with affiliation, sector
(academic/industry), seniority bucket, paper titles, abstracts, and links.

Outputs are Google-Sheets-friendly CSVs ready for outreach.

---

## Quick start

```bash
# 1. Copy the example config and edit conference/year/areas/countries
cp assets/config_example.json my_run.json
$EDITOR my_run.json

# 2. Run the full pipeline
python3 scripts/pipeline.py --config my_run.json

# 3. Results land in the output_dir from your config
ls ./output/
```

A run on a full CVPR-sized venue (~4,000 papers) takes 15–25 minutes:

- ~5 min scraping the virtual conference site
- instant keyword classification
- ~10 min bulk arxiv fetch + parallel PDF parsing
- ~2 min OpenAlex enrichment
- a few seconds formatting

Each stage checkpoints to JSON/CSV so a failed stage can be re-run without redoing earlier
work.

---

## Pipeline steps (what actually happens)

This skill is the productionized version of a pipeline we built and debugged from scratch.
Each step below also lists what we tried that **didn't** work, so future maintainers don't
walk the same path.

### 1. Scrape the conference paper list

**CVF venues (CVPR / ICCV / ECCV / WACV)** — scrape the virtual site (e.g.
`cvpr.thecvf.com/virtual/2026/papers.html`). Each poster page yields title, authors
(separated by `⋅`), and abstract (under `<div class="abstract-content">`).

**OpenReview venues (NeurIPS / ICLR / ICML / COLM)** — query the OpenReview API v2 for
all accepted submissions under the venue group.

Notes from the field:
- **CVPR is NOT on OpenReview** for the main conference, despite a `thecvf.com/CVPR/...`
  group existing there. The main track uses Microsoft CMT. Only workshop proposals live
  on OpenReview. We confirmed 0 results when first attempting the OpenReview path. CVF
  virtual site is the proven source for CVPR.
- The virtual site contains author names but **no affiliations** anywhere — that has to
  come from arxiv (step 3).

### 2. Classify papers into target research areas

Keyword/regex classifier — each target area has a list of patterns, a paper matches if any
pattern hits its title or abstract.

Why regex and not an LLM:
- Runs in milliseconds on ~4k papers
- No API key dependency
- Generous patterns ("3D Reconstruction" matches `\bnerf\b`, `\bgaussian splatting\b`,
  `\bsfm\b`, etc.) give acceptable precision/recall
- For higher accuracy, an Anthropic API key can substitute Claude classification — see
  `references/llm_classifier.md`

Output: subset of papers that match at least one target area (typically ~25% of submissions).

### 3. Enrich with affiliations via arxiv (the critical step)

This is the load-bearing step and the one with the most debug history.

**What works** — bulk arxiv fetch + local title match + parallel PDF first-page parse:

1. Query arxiv API for ALL papers in `cs.CV`, `cs.AI`, `cs.LG`, `cs.RO`, `cs.GR`, `cs.MM`
   within the conference's preprint window (e.g. Sep 2025 – May 2026 for CVPR 2026).
   Date-window the queries in 1–2-month slices because arxiv 500s on `start > ~10000`
   in a single query.
2. Cache locally as `arxiv_index.json` (~80k papers, ~30 MB).
3. Locally fuzzy-match each matched conference paper title to the arxiv index. ~65% of
   CVPR papers match.
4. Download matched arxiv PDFs in parallel (12 workers).
5. Extract first page text via `pdfminer.six`.
6. Regex-parse numbered affiliation lines (`1MIT 2Adobe Research 3UCL`) and superscript-
   tagged author names. Map author position → affiliation index.
7. Infer country from affiliation string via a hand-curated keyword table.

**What didn't work**:

- **Semantic Scholar API** — returned HTTP 429 (rate limited) on every request. Script
  silently swallowed the errors, producing 0% coverage. Would work with an S2 API key.
- **OpenAlex paper-search → author IDs** — OpenAlex hasn't indexed CVPR 2026 papers' author
  IDs yet (they're `null`), and naive name-only matching returned wrong same-name people
  (e.g. "Hao Dong" matched to "China Tobacco" instead of Peking University).
- **OpenAlex author-name search with disambiguation by co-author** — same noisy result,
  high false-positive rate for common Chinese names.
- **Per-title arxiv search (one query per paper)** — works but arxiv rate-limits at ~3s
  per query → 60 min for 1000 papers AND was buggy: our `<title>` regex matched the feed's
  query echo, not the entry's paper title, rejecting valid matches. Bulk approach fixes both.

Final coverage: ~50% of authors get a confident affiliation from this step. The other ~50%
fall into `*_unknown_country.csv` (no arxiv preprint OR PDF parse glitch).

### 4. Country filter

Country codes derived in step 3 are filtered against a user-specified keep-list. Common
presets (`references/country_presets.md`):

- `us_friendly_western`: US, CA, GB, all EU + EFTA, IL
- `english_speaking`: US, CA, GB, IE, AU, NZ
- `india_inclusive`: above + IN

Hong Kong (HK) and Taiwan (TW) are tracked separately from mainland China (CN) — include
or exclude explicitly. Authors with unknown country are kept in a separate CSV so they
can be enriched manually or re-processed later.

### 5. Add sector + seniority via OpenAlex

For each shortlisted author, query the OpenAlex authors endpoint by name. Disambiguate
candidates by checking whether their `last_known_institutions` matches the arxiv-derived
affiliation. From the picked candidate:

- `works_count` and `h_index` → seniority bucket
- Affiliation regex → sector (academic / industry / mixed)
- `homepage_url` (rarely populated in OpenAlex — ~5% hit rate)

Seniority buckets:

| Bucket | works_count | h_index |
|---|---|---|
| Senior (Faculty/Principal) | ≥ 80 | OR ≥ 30 |
| Mid (Postdoc/Sr.Researcher) | ≥ 30 | OR ≥ 15 |
| Junior (Late PhD/Early career) | ≥ 5 | — |
| Junior (PhD student?) | ≥ 1 | — |

This is best-effort — common names ("Hao Li", "Bo Li") will collapse multiple distinct
researchers into one record with inflated stats. Spot-check senior outliers.

### 6. (Optional) Phase D — find homepage + position

Per-author search-engine scrape to find personal homepages, then regex for position
(Professor, PhD Student, Research Scientist, etc.).

**Status**: blocked without a search-API key. DuckDuckGo and Brave's free HTML interfaces
rate-limit aggressively (~20 queries before 100% throttle). The skill includes a Brave
Search API key path (free signup, 2k queries/month). See `references/phase_d_homepage.md`.

Without a key, this step is skipped — `homepage` and `position` columns stay empty.

### 7. Format outputs

Each stage's CSVs are re-exported in three shapes plus an abstract one-liner per paper:

- **Wide** — one row per author, papers joined in one cell
- **Long** — one row per author×paper
- **Wide-papers** — one row per author with explicit `paper_1_title/url/abstract` …
  `paper_N_*` columns (best for CRM imports and mail-merge)

All CSVs are written with `csv.QUOTE_ALL` for clean Google Sheets import — embedded
newlines and commas in abstracts/affiliations won't break the import.

---

## Origin story (provenance of this skill)

This skill is the cleaned-up version of a pipeline built in a single Claude Code session
targeting CVPR 2026 hiring. The session went through several false starts that informed
the design here:

1. First attempt used `openreview-py` against `thecvf.com/CVPR/2026/Conference` → 0 results
   (CVPR isn't on OpenReview). Pivot: scrape `cvpr.thecvf.com/virtual/2026/papers.html`.
2. Second attempt used Anthropic API for classification → user didn't have a key. Pivot:
   regex/keyword classifier (works for the common research areas with carefully written
   patterns; less accurate for nuanced topics).
3. Third attempt used Semantic Scholar for affiliations → 429 on every request, 0%
   coverage. Pivot: OpenAlex.
4. Fourth attempt used OpenAlex paper-search → too noisy on recent papers (author IDs not
   yet linked, wrong same-name matches). Pivot: arxiv PDF scrape.
5. Fifth attempt used per-title arxiv search → rate-limited and buggy. Pivot: bulk arxiv
   fetch + local fuzzy match + parallel PDF parse. **This is the path that worked.**
6. Phase D homepage scrape via DDG → rate-blocked after 20 queries. Pivot: Brave HTML →
   same problem. Resolution: documented Brave Search API key path as optional add-on.

Result on the original CVPR 2026 run:
- 4,070 papers scraped
- 959 matched to target areas (10 areas covering pose/segmentation/3D/robotics/VLA/etc.)
- 5,289 unique authors across those papers
- 590 in US/CA/UK/EU/India keep-list with confirmed affiliations
- 321 academic, 189 industry, 46 mixed sectors
- 288 Senior, 120 Mid, 179 Junior by seniority bucket

---

## Limitations to surface in any report to the user

1. ~30–50% of authors have unknown affiliation (no arxiv preprint we could match)
2. Same-name researchers silently merge — spot-check common names
3. Multi-affiliation papers may pick the wrong primary country
4. PDF parse noise (~5% of affils are garbage from figure captions or abstract fragments)
5. Regex classifier misses topics phrased outside the keyword list
6. Position/homepage columns are empty unless a Brave Search API key is configured

See `references/known_limitations.md` for the full list and mitigation strategies.

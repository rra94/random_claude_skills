---
name: conference-scout
description: |
  End-to-end pipeline that turns a conference (CVPR, ICCV, ECCV, NeurIPS, ICML, ICLR) and
  a list of research areas into a hireable-authors shortlist CSV — with affiliation, country,
  academic/industry sector, seniority bucket, paper titles, abstracts, and links.

  Use this skill whenever the user asks anything like: "find researchers/authors from
  <conference> <year> working on <topic>", "build a hiring list from CVPR", "who wrote the
  best <topic> papers at ICLR", "give me a recruiting CSV from NeurIPS", "shortlist candidates
  from <conference> in the US/Europe", or "scout <conference> for engineers in <area>".
  Trigger even if the user doesn't say "hiring" — any "list of researchers from a conference
  filtered by topic / location / seniority" task should use this.
---

# conference-scout

Builds a recruiter-grade shortlist of researchers from a major ML/CV conference, filtered
by topic and country, enriched with affiliation, sector, seniority, and per-paper context.

This is a long-running file-producing pipeline (~15–25 min for a typical run). Stages:

1. **Scrape** the conference paper list (titles, authors, abstracts, URLs).
2. **Classify** papers into the user's target research areas via regex/keyword matching.
3. **Enrich** with affiliations via arxiv bulk fetch + per-paper PDF first-page parsing.
4. **Resolve** each affiliation against the ROR registry — gives authoritative
   institution name, ISO country code, and sector (academic/industry/government/nonprofit).
5. **Filter** authors to the user's country keep-list.
6. **Add seniority** via OpenAlex author records (works_count, h_index).
7. **Format** outputs into Sheets-friendly CSVs (wide, long, and one-row-per-author with
   `paper_N_title/url/abstract` columns).

## When to use this skill

Trigger for any task that needs **researchers from a conference, filtered**. Examples:

- "Find authors from CVPR 2026 doing pose estimation we could hire"
- "Build a list of NeurIPS 2025 RL researchers in the US and Europe"
- "Who at ICCV 2025 is working on robot learning — academia or industry?"
- "Scout ICLR 2026 for VLM researchers, exclude China and Hong Kong"

Don't use it for: a single specific researcher lookup, paper-citation analysis, or generic
"summarize this conference" tasks — those need different tooling.

## Inputs the user must specify

Before running, get from the user (ask if missing):

| Input | Example | Notes |
|---|---|---|
| Conference + year | "CVPR 2026", "ICLR 2026" | Determines scrape source |
| Target research areas | `["Pose Estimation", "VLA", "Robot Learning"]` | Map to regex patterns; see `references/area_patterns.md` |
| Country keep-list | `["US", "GB", "DE", ...]` | ISO 3166-1 alpha-2 codes; preset bundles in `references/country_presets.md` |
| Output directory | `./<conference>_<year>_scout/` | Where all CSVs land |

If the user is vague ("US and Europe"), use the preset bundles documented in
`references/country_presets.md` rather than guessing.

## How to run

Build a config (see `assets/config_example.json` for the schema) and run:

```bash
python3 scripts/pipeline.py --config path/to/config.json
```

The orchestrator runs each stage and checkpoints intermediate results so a failed stage
can be re-run without redoing earlier work. Each stage can also be run standalone — useful
for debugging or partial reruns. See `references/orchestration.md` for details.

Outputs land in the config's `output_dir`:

- `papers_raw.json` — every scraped paper with title/authors/abstract
- `papers_matched.json` — papers matched to target areas
- `<conf>_candidates.csv` — one row per author×paper (wide-table-friendly)
- `<conf>_unique_authors.csv` — one row per author, deduped by name
- `<conf>_authors_arxiv.csv` — adds affiliation + country from arxiv parsing
- `<conf>_filtered.csv` — country-filtered subset (the "shortlist")
- `<conf>_shortlist.csv` — filtered + sector/seniority/openalex enrichment
- `<conf>_shortlist_wide_papers.csv` — one row per author, `paper_N_title/url/abstract` columns
- `<conf>_shortlist_long.csv` — exploded one row per author×paper
- `<conf>_unknown_country.csv` — authors whose country couldn't be resolved

All CSVs are written with `csv.QUOTE_ALL` so they import cleanly into Google Sheets.

## Picking the right scrape strategy

The skill supports two strategies; pick by conference:

| Conference | Strategy | See |
|---|---|---|
| CVPR, ICCV, ECCV, WACV | CVF virtual site scrape | `references/cvf_strategy.md` |
| ICLR, NeurIPS, ICML, COLM, TMLR | OpenReview API | `references/openreview_strategy.md` |

CVPR-style sites give titles + authors + abstracts but no affiliations → arxiv enrichment
is essential. OpenReview venues sometimes include affiliations directly in submission
metadata (depends on the venue's submission form).

## Building target-area regex patterns

The classifier is keyword/regex based — fast but imperfect. Each target area gets a list of
regex patterns; a paper matches if any pattern hits its title or abstract. See
`references/area_patterns.md` for:

- How to write generous-yet-precise patterns
- A library of patterns for common CV/ML areas (pose, segmentation, NeRF/3DGS, depth, world
  models, robot learning, VLA, etc.)
- When to add a new area vs. expanding an existing one

For higher-precision classification, two stronger options are available:
- `classify_hybrid.py` — runs regex first then asks Claude to confirm/reject each match
  (best precision/cost tradeoff, requires `ANTHROPIC_API_KEY`, see `references/llm_classifier.md`)
- Full LLM classification on every paper (see `references/llm_classifier.md`)

The default regex classifier is sufficient for most uses.

## Country filtering

The filter operates on ISO country codes derived during arxiv enrichment. Common presets in
`references/country_presets.md`:

- `us_friendly_western`: US, CA, GB, all EU + EFTA, IL
- `us_only`: US, PR
- `english_speaking`: US, CA, GB, IE, AU, NZ
- `india_inclusive`: above + IN

The user can compose their own list. Hong Kong (HK) and Taiwan (TW) are tracked separately
from China (CN) — include or exclude explicitly.

## Sector + seniority

`sector` (academic / industry / government / nonprofit / other) comes from the ROR
registry's `organization.types` whenever ROR confidently resolves an affiliation
(score ≥ 0.7). A regex classifier handles the residual rows where ROR returns no match.

For `seniority`, the OpenAlex enrichment step pulls each author's `works_count` +
`h_index` + `homepage_url` and buckets them:

| Bucket | works_count | h_index |
|---|---|---|
| Senior (Faculty/Principal) | ≥ 80 | OR ≥ 30 |
| Mid (Postdoc/Sr.Researcher) | ≥ 30 | OR ≥ 15 |
| Junior (Late PhD/Early career) | ≥ 5 | — |
| Junior (PhD student?) | ≥ 1 | — |

Same-name disambiguation is best-effort — see "Known limitations" below.

## Output shapes (for downstream tools)

Three CSV shapes for the same data. Pick by use case:

| File | Shape | Best for |
|---|---|---|
| `<conf>_shortlist.csv` | 1 row per author; papers joined in one cell | Quick browse, sorting by seniority |
| `<conf>_shortlist_long.csv` | 1 row per author×paper | Pivot tables, filtering by paper or area |
| `<conf>_shortlist_wide_papers.csv` | 1 row per author; `paper_1_title/url/abstract`…`paper_N_*` columns | CRM imports, mail-merge tools |

## Known limitations — surface these proactively to the user

1. **Affiliation coverage ≈ 50–70%**. ~30% of conference papers have no arxiv preprint
   we can match (industry-only papers, very late preprints). Those authors land in
   `*_unknown_country.csv` with no affiliation. Tell the user this upfront.

2. **Same-name dedupe is naive**. "Hao Li", "Bo Li", "Yi Yang" silently collapse multiple
   distinct researchers into one row, inflating their paper count and OpenAlex stats.
   Spot-check senior outliers with common names.

3. **Multi-affiliation papers** pick the first parsed institution per paper, then take the
   majority across an author's papers. May label someone "US" when their primary lab is
   in CN/HK if they have a US visiting affiliation listed first.

4. **Position/homepage scraping (Phase D) is blocked without an API key**. DuckDuckGo and
   Brave's free HTML interfaces rate-limit after ~20 queries. To populate `homepage` and
   `position` for the shortlist, the user needs a free Brave Search API key (sign-up at
   <https://api-dashboard.search.brave.com/>, 2k queries/month). Without it, those columns
   stay mostly empty. See `references/phase_d_homepage.md`.

5. **Regex classifier misses nuanced topics**. A paper on "novel view synthesis" won't
   match `\b3d reconstruction\b` even though they're related. Generous keyword sets help
   but won't catch everything; consider LLM-based classification for higher-stakes runs.

6. **PDF parse noise**. Roughly 5% of parsed affiliations are garbage (figure captions or
   abstract fragments mistaken for institution names). Flag obviously-malformed rows when
   showing the user the shortlist.

7. **Arxiv rate limits**. The bulk arxiv index build does ~50 paginated queries at 3 s/req
   (≈3 min). If it 500s mid-stream, the script retries up to 3× then moves on; the cached
   index persists across runs.

## Files

```
conference-scout/
├── SKILL.md                          (this file)
├── scripts/
│   ├── pipeline.py                   orchestrator — run end-to-end
│   ├── scrape_cvf.py                 CVF virtual site scraper
│   ├── scrape_cvf_openaccess.py      optional post-conference CVF Open Access PDF scrape
│   ├── scrape_openreview.py          OpenReview API scraper
│   ├── classify.py                   regex/keyword paper classifier
│   ├── classify_hybrid.py            optional: regex recall → Claude precision filter
│   ├── enrich_arxiv.py               arxiv bulk fetch + PDF parse (GROBID if available); extracts emails
│   ├── grobid_parse.py               GROBID TEI parser helper (optional Docker dep)
│   ├── ror_resolve.py                ROR registry → country + sector (parallel)
│   ├── openreview_profile_fallback.py  optional fallback for unknown-country authors
│   ├── enrich_openalex.py            OpenAlex seniority + disambiguation confidence
│   ├── enrich_s2.py                  Semantic Scholar alternative (OpenAlex went paid in 2026)
│   ├── filter_countries.py           country keep-list filter
│   └── format_output.py              produces all CSV shapes
├── references/
│   ├── cvf_strategy.md
│   ├── openreview_strategy.md
│   ├── area_patterns.md              regex pattern library + how to write more
│   ├── country_presets.md            named country bundles
│   ├── ror_strategy.md               how ROR resolves affiliation → country + sector
│   ├── grobid_setup.md               optional Docker-based PDF parser (better affil quality)
│   ├── orchestration.md              how to re-run individual stages
│   ├── phase_d_homepage.md           Brave API setup (optional homepage enrichment)
│   ├── llm_classifier.md             swap in Anthropic API for higher classification accuracy
│   └── known_limitations.md
└── assets/
    └── config_example.json           sample config users copy & edit
```

## Reporting results to the user

After running, summarize like this:

```
Done. Pipeline produced N shortlisted authors at <output_dir>.

  By country:    US <n>, GB <n>, ...
  By sector:     academic <n>, industry <n>, mixed <n>
  By seniority:  Senior <n>, Mid <n>, Junior <n>

  Coverage:      <n>/<total> matched papers found on arxiv (~Y%)
  Unknown:       <n> authors in *_unknown_country.csv (no affil)

Files:
  cvpr2026_shortlist.csv               primary outreach list
  cvpr2026_shortlist_wide_papers.csv   for CRM imports
  cvpr2026_shortlist_long.csv          for pivot analysis

Caveats to spot-check: <list any flags from "Known limitations" that affected this run>
```

Always include the caveats — they materially affect outreach quality.

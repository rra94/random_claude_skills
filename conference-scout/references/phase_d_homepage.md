# Phase D — Homepage and position enrichment

This is optional. Without it, the `homepage` and `position` columns in the shortlist will
be mostly empty.

## Why a search-engine API key is required

We tried two anonymous fallbacks first:

- **DuckDuckGo HTML** (`html.duckduckgo.com/html/`) — returned 202 (queue/throttle) after
  ~20 queries from one IP. Useless at the 500-author scale.
- **Brave Search HTML** (`search.brave.com/search`) — same outcome. Works for ~25 queries
  then 0 results.

Both engines have switched to API-only access for sustained scraping. There's no anonymous
path that reliably gives 500+ queries.

## Brave Search API (recommended)

Free tier is enough for typical conference runs (2,000 queries/month, 1 query/second).

1. Sign up at <https://api-dashboard.search.brave.com/register>
2. Generate an API key (no credit card required for free tier)
3. Paste into your config:

```json
"brave_api_key": "BSAxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

4. Run the optional Phase D stage:

```bash
python3 scripts/phase_d_homepage.py --config my.json
```

(This script is not yet bundled — see "Implementation sketch" below.)

## What Phase D does

For each shortlisted author:

1. Brave API search: `"<name>" <short_affil>` → top 5 results
2. Filter out known non-personal domains (LinkedIn, Scholar, arxiv, ResearchGate, etc.)
3. Take the first remaining hit as `homepage`
4. Fetch the page, regex for position keywords:
   - Faculty: Assistant/Associate/Full Professor, Lecturer, Reader
   - Research staff: Research Scientist, Senior/Staff/Principal Research Scientist,
     Member of Technical Staff, Research Engineer
   - Postdoc, PhD Student, Masters Student
   - Leadership: VP, CTO, Director, Head of
   - Founder, Co-Founder

## Implementation sketch (`phase_d_homepage.py`)

```python
# api_url = "https://api.search.brave.com/res/v1/web/search"
# headers = {"Accept": "application/json", "X-Subscription-Token": cfg["brave_api_key"]}
# for each author in shortlist:
#   results = GET api_url ?q=quote("<name> affil_short")
#   pick first non-skiplist URL
#   GET that URL → bs4 → regex for POSITION_PATTERNS → fill columns
```

The position regex set used previously (in `/Users/rishav_gritt/cvpr2026/phase_d.py`) is a
good starting point — copy it over.

## Without Phase D

The pipeline still produces a usable shortlist. The `homepage` column will be empty (3-5%
of authors get one from OpenAlex's `homepage_url` field). The `seniority` bucket is still
populated from `works_count` + `h_index`, which is the more reliable signal anyway.

For outreach, use the `linkedin_search` column as the manual fallback for finding
homepages — clicking it opens a pre-filled LinkedIn people search.

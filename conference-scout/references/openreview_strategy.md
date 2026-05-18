# OpenReview strategy

OpenReview is the canonical source for ICLR, NeurIPS (main + datasets), ICML, COLM, TMLR,
and select workshops at CVPR/ECCV (workshop tracks only).

## Venue IDs

Use the venue group ID exactly as it appears in the OpenReview URL:

| Conference | venue_id |
|---|---|
| ICLR 2026 | `ICLR.cc/2026/Conference` |
| NeurIPS 2025 | `NeurIPS.cc/2025/Conference` |
| NeurIPS 2025 Datasets & Benchmarks | `NeurIPS.cc/2025/Track/Datasets_and_Benchmarks` |
| ICML 2025 | `ICML.cc/2025/Conference` |
| COLM 2025 | `colmweb.org/COLM/2025/Conference` |
| TMLR | `TMLR/Authors` (continuously published; year-filter post-hoc) |

For unsure venues, navigate to the conference's OpenReview landing page and read the URL.

## What's available

OpenReview submissions carry richer metadata than CVF: in addition to title/authors/abstract,
many venues also include:
- `keywords` (author-provided tags)
- `TL;DR` (short one-line summary)
- `authorids` (OpenReview author profile IDs — may resolve to affiliations via `get_profiles`)

Whether affiliations are reliably extractable depends on the venue's submission form. ICLR
and ICML profiles usually have current institutions; NeurIPS is hit-or-miss for older years.

## What the scraper does

1. Init `OpenReviewClient` against `https://api2.openreview.net`.
2. `client.get_all_notes(invitation=f"{venue_id}/-/Submission")`.
3. Filter to those whose `content.venueid.value` contains `venue_id` (drops withdrawn/rejected).
4. Extract title, authors, authorids, abstract, keywords → `papers_raw.json`.

## Why we don't currently fetch affiliations via OpenReview profiles here

We tried — `client.get_profiles(authorids)` returns a `last_known_institution` field, but:
- Coverage is uneven across venues
- The arxiv enrichment path already covers everyone with a preprint
- Trying both can produce conflicting affiliations (OpenReview profile vs arxiv first page);
  arxiv is more current

If you need OpenReview-profile affiliations, extend `enrich_arxiv.py` with a parallel
OpenReview profile fetch and merge the results, preferring arxiv when both exist.

## Common pitfalls

- `Submission` is the standard invitation but some venues use `Blind_Submission` or
  `Camera_Ready` — if the standard query returns 0, try those.
- CVPR/ICCV main tracks are **not** on OpenReview. The skill's `scrape_cvf` is the right
  path for those.
- The CVPR/ICCV workshop tracks ARE on OpenReview (`thecvf.com/CVPR/2026/Workshop/<NAME>`).
  Use those venue IDs to scout workshop authors specifically.

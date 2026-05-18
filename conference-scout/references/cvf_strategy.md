# CVF virtual site strategy

CVF (Computer Vision Foundation) hosts CVPR, ICCV, ECCV, WACV on virtual sites with a
consistent URL pattern:

- CVPR: `https://cvpr.thecvf.com/virtual/<YEAR>/papers.html`
- ICCV: `https://iccv.thecvf.com/virtual/<YEAR>/papers.html`
- ECCV: `https://eccv.ecva.net/virtual/<YEAR>/papers.html`
- WACV: `https://wacv.thecvf.com/virtual/<YEAR>/papers.html`

(Confirm the URL by visiting it before running — the path format changes year over year.)

## What the scraper does

1. GET the index page → all `<a href="/virtual/<YEAR>/poster/<ID>">` links → paper list.
2. For each paper, GET the poster page in parallel (16 workers default).
3. Extract:
   - **Title**: from `<title>` or anchor text
   - **Authors**: from any line containing the middle-dot separator `⋅`
   - **Abstract**: from `<div class="abstract-content">`

## What's NOT on the CVF site

- **No affiliations anywhere** — we verified via grep for "institution/affiliation/university"
  keywords (0 hits on poster pages). Only names.
- **No author profile links** — author tokens are plain text, not links.
- **No JSON/API endpoint** — paper data is server-rendered HTML only.

This is why arxiv enrichment (step 3) is essential: it's the only way to get affiliations.

## Common pitfalls

- The virtual site won't have CVPR data until the conference's "virtual platform launch",
  typically 4–6 weeks before the conference. Before that, you'll get 404 or an empty index.
- For CVPR specifically, do not use OpenReview — CVPR uses Microsoft CMT, only workshop
  proposals appear on OpenReview.
- The middle-dot is U+22C5 (⋅), not the regular bullet (•) or interpunct (·). Don't change
  it in the parser without testing.

## Schema written to `papers_raw.json`

```json
[
  {
    "paper_id": "37468",
    "title": "...",
    "url": "https://cvpr.thecvf.com/virtual/2026/poster/37468",
    "authors": ["First Last", "..."],
    "abstract": "..."
  }
]
```

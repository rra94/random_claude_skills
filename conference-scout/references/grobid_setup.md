# GROBID setup (optional, recommended for affiliation quality)

GROBID is an ML-based PDF→TEI extractor for scholarly documents. It's the production
parser used by Semantic Scholar, ResearchGate, and HAL. Compared to the default
pdfminer + regex affiliation parser, GROBID:

- Parses author/affiliation/email/ORCID with proper structural understanding
- Natively links each author to their affiliations (no superscript-digit guessing)
- Returns ISO 3166-1 country codes directly from TEI `<country>` elements
- Handles unusual PDF layouts (CVF camera-ready, multi-column formats) much better

Without GROBID, the skill falls back to pdfminer + regex. That works for ~75–80% of
arxiv preprints. Turning GROBID on lifts affiliation quality to ~95% on the same papers
and cuts the "garbage strings from figure captions" failure mode (limitation #4 in
`known_limitations.md`).

## One-time setup

GROBID runs as a Docker service. Install Docker, then:

```bash
docker run --rm -d --name grobid -p 8070:8070 lfoppiano/grobid:0.8.2
# Or the full deep-learning image (slower, slightly better):
docker run --rm -d --name grobid -p 8070:8070 lfoppiano/grobid:0.8.2-full
```

The image is ~700 MB; first pull takes a few minutes. After it's up:

```bash
curl http://localhost:8070/api/isalive
# Expected response: true
```

## Enable in your config

```json
"grobid": {
  "enabled": true,
  "url": "http://localhost:8070"
}
```

`enrich_arxiv` auto-detects GROBID at startup. If reachable, it routes every PDF through
GROBID; if not, it logs a warning and falls back to pdfminer. No re-run needed when
toggling — the cached `pass_c_results.json` is keyed per paper so just delete it (or run
only the unprocessed papers) when switching parsers.

## Cost / runtime

GROBID adds ~2–5 seconds per PDF on the lightweight image (single-threaded; the
ThreadPoolExecutor in `enrich_arxiv` keeps the queue full). On the `-full` image it's
~5–10 s but with slightly better extraction quality.

For a typical 600-PDF run:
- pdfminer-only: ~2 min total (12 workers × ~2 s each)
- GROBID (`0.8.2` lite): ~5 min total
- GROBID (`0.8.2-full`): ~10 min total

The quality jump on borderline PDFs is usually worth the extra few minutes.

## When NOT to use GROBID

- You're on a machine without Docker
- You're doing a small / iteration run and pdfminer is "good enough"
- The conference's PDFs are mostly well-formed arxiv preprints (pdfminer handles those
  acceptably without needing the structural parse)

## Troubleshooting

- **"GROBID configured but not reachable"** in the log → `docker ps` to confirm the
  container is running; check it's mapped to port 8070; try `curl localhost:8070/api/isalive`
- **TEI XML parse errors** are silently skipped per-paper (the fallback kicks in for those)
- **GROBID is slow** → use the lite image (`0.8.2` not `0.8.2-full`); raise
  `config.arxiv.pdf_workers` to 24+ (GROBID handles parallel requests fine)

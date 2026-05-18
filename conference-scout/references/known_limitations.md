# Known limitations

Always surface the relevant ones to the user when reporting results — they materially
affect outreach quality.

## 1. Affiliation coverage is incomplete (~50–70%)

**Symptom**: `<conf>_unknown_country.csv` is non-empty, often 30–50% of unique authors.

**Cause**: not every conference paper has an arxiv preprint we can match.
- ~10% of papers have no arxiv version at all (industry-only, late submissions)
- ~10% have an arxiv version we can't find via title fuzzy match (title changed between
  preprint and camera-ready)
- ~10% match arxiv but PDF parsing fails (unusual layout, scanned/image-only PDFs)

**Mitigation**:
- After the conference's CVF Open Access proceedings are published (June–July for CVPR),
  re-scrape from `openaccess.thecvf.com` — covers 100% of accepted papers
- For high-value targets, manually look them up

## 2. Same-name dedupe collapses distinct researchers

**Symptom**: "Hao Li" has 7 matched papers spanning unrelated areas; "Bo Li" has 6;
"Yi Yang" has 6. Their seniority bucket shows Senior despite half of them being PhD students.

**Cause**: dedupe is by exact name string. CS has many duplicate names, especially Chinese
and Korean names romanized identically. ~5–10% of common names are silent merges.

**Mitigation**:
- Spot-check senior outliers — if affiliation looks consistent across all their papers,
  it's probably one person; if affiliations jump between US/CN/CN/CH it's likely multiple
- Future work: use OpenAlex author IDs (already pulled, stored in `openalex_id`) as the
  authoritative key

## 3. Multi-affiliation papers pick the wrong primary country

**Symptom**: An author with papers from "Nanjing University, 2Visiting at Stanford" gets
labeled US.

**Cause**: each parsed affiliation is counted equally and the plurality wins. For
visiting-scholar papers, the secondary US affiliation may match equally often as the
primary CN one.

**Mitigation**:
- Inspect the `ror_name` and `affiliation` columns directly — they show the picked institution
- If the affiliation string starts with a CN/HK institution but `ror_country=US`, that's a
  false positive
- The `ror_score` column shows ROR's match confidence — scores ≥0.9 are very reliable;
  0.7–0.9 warrant a glance

## 4. PDF parse noise (~5% of affiliations are garbage)

**Symptom**: A row's `affiliation` field reads "B dataset provides multi-granularity
annotations includ-" or similar arbitrary text.

**Cause**: the affiliation regex matches any line starting with a digit that contains an
institution keyword. Some papers' first pages have figure captions, table rows, or paragraph
breaks that look like numbered affiliations.

**Mitigation**:
- Filter shortlist on `affiliation` strings containing actual institution keywords
- For the worst offenders, manually inspect their PDFs

## 5. Regex classifier misses topics phrased outside the keyword list

**Symptom**: "Novel view synthesis" papers don't match `3D Reconstruction` despite being
closely related.

**Cause**: keyword matching has no semantic understanding.

**Mitigation**:
- Add the missed phrasings to your area's pattern list and re-run `classify` stage
- See `references/llm_classifier.md` for LLM-based classification

## 6. OpenAlex same-name disambiguation is best-effort

**Symptom**: "Xing Zhu" gets `works_count=3266`, `h_index=106` — way too high for a real
person in CV; that's all "Xing Zhu"s in OpenAlex collapsed.

**Cause**: disambiguation matches the author's arxiv-derived affiliation against OpenAlex
candidates' `last_known_institutions`. When no candidate matches the affiliation, the
fallback is the top textual-match candidate — which may be a different person entirely.

**Mitigation**:
- Treat `seniority` as a rough bucket, not exact
- For common Chinese/Korean names, expect noise; verify the OpenAlex ID URL before quoting
  numbers in outreach

## 7. Position / homepage columns are empty without a Brave API key

**Symptom**: `homepage` and `position` columns mostly blank.

**Cause**: anonymous search-engine scraping (DDG, Brave HTML) rate-limits hard after ~20
queries.

**Mitigation**: see `references/phase_d_homepage.md` — free Brave Search API key fixes it.

## 8. arxiv rate limits during bulk index build

**Symptom**: `[cs.AI 202509-202510] start=10000 status=500` repeated in logs.

**Cause**: arxiv caps single-query results around 10,000. The skill splits queries into
1-month windows to stay under, but a particularly busy category in a busy month can still
hit it.

**Mitigation**: script retries 3× then moves on. The cached `arxiv_index.json` persists, so
a partial fetch is still useful. To improve coverage, split the relevant date window in
`config.arxiv.date_windows` into shorter slices.

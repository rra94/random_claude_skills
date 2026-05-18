# Country code presets

The country filter uses ISO 3166-1 alpha-2 codes. Common bundles below — copy into your
config's `filter.keep_countries`.

## `us_friendly_western`

US + EU + UK + EFTA + Israel. Default in `config_example.json`.

```json
["US", "CA", "GB",
 "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
 "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
 "PL", "PT", "RO", "SK", "SI", "ES", "SE",
 "CH", "NO", "IS", "LI", "IL"]
```

## `us_only`

```json
["US", "PR"]
```

## `english_speaking`

```json
["US", "CA", "GB", "IE", "AU", "NZ"]
```

## `india_inclusive` (adds India to us_friendly_western)

```json
["US", "CA", "GB", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE",
 "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT",
 "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
 "CH", "NO", "IS", "LI", "IL", "IN"]
```

## `apac` (Asia-Pacific, excluding China)

```json
["JP", "KR", "SG", "HK", "TW", "AU", "NZ", "IN"]
```

## How country detection works

In `enrich_arxiv.py`:
1. We extract affiliations from the first page of each paper's arxiv PDF
2. For each affiliation string, we try to detect a country via:
   - **Direct country-name match** ("University of X, USA" → US)
   - **Known-institution heuristic** ("MIT" → US, "ETH" → CH, "Tsinghua" → CN, etc.)
3. Per author, we vote across all their matched papers' affiliation countries; the
   plurality wins

The keyword tables for both detection methods are inside `scripts/enrich_arxiv.py`. To add
a country or institution mapping, edit `COUNTRY_HINTS` or `INSTITUTION_COUNTRY` and re-run
the enrich stage.

## Caveats

- **Hong Kong (HK), Taiwan (TW), Macau (MO)** are tracked separately from mainland China
  (CN). Be explicit about whether to include each.
- **Authors with no detectable country** (PDF parse failed or no arxiv preprint) land in
  `<conf>_unknown_country.csv`. They are NOT included in `<conf>_filtered.csv`.
- **Multi-affiliation papers** (e.g. visiting scholar) may resolve to a non-primary country.
  Spot-check authors who appear in surprising countries.

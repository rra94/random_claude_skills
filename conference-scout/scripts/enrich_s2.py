"""Semantic Scholar alternative to enrich_openalex.

Uses Semantic Scholar Graph API to pull each shortlisted author's h_index,
citationCount, paperCount, affiliations, homepage. Same output columns as
enrich_openalex (works_count, h_index, openalex_id, seniority, homepage,
openalex_confidence) so format_output and downstream views work unchanged —
but populated from S2 instead of OpenAlex.

Why this exists: OpenAlex moved to a paid model in 2026 ($1/day free tier),
which exhausts mid-run on conference-sized inputs. S2 has a free API tier
that's more generous when you have an API key (free signup at
https://www.semanticscholar.org/product/api).

Rate limits:
  - With S2 API key:    ~100 req/sec, more than enough for any conference run
  - Without API key:    1 req/sec (still survivable for typical conference sizes)

Reads:  <output_dir>/<conf>_filtered.csv
Writes: <output_dir>/<conf>_shortlist.csv  (same schema as enrich_openalex output)

Config knobs:
  "s2": {
    "api_key": null,         // set to your S2 key string (env S2_API_KEY also picked up)
    "sleep_seconds": 0.05    // bump if unauthenticated (no key)
  }
"""
import argparse, json, os, re, time
import requests
import pandas as pd

# Reuse the sector classifier + seniority bucket from enrich_openalex
from enrich_openalex import (
    classify_sector, seniority_bucket, normalize,
)

S2_API = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "name,hIndex,citationCount,paperCount,affiliations,homepage,url"


def make_session(api_key: str | None):
    s = requests.Session()
    s.headers["User-Agent"] = "conference-scout/0.1"
    if api_key:
        s.headers["x-api-key"] = api_key
    return s


def s2_author_search(session, name: str, retries: int = 3) -> list[dict]:
    """Return S2 author candidates ordered by S2's relevance score."""
    for attempt in range(retries):
        try:
            r = session.get(f"{S2_API}/author/search",
                            params={"query": name, "limit": 5, "fields": S2_FIELDS},
                            timeout=15)
            if r.status_code == 200:
                return (r.json() or {}).get("data", []) or []
            if r.status_code in (429, 503):
                # rate-limited: back off
                time.sleep(2 ** attempt)
                continue
            return []
        except Exception:
            time.sleep(2 ** attempt)
    return []


def affil_matches(cand: dict, expected_affil: str) -> bool:
    expected = normalize(expected_affil)
    if not expected: return False
    for affil in (cand.get("affiliations") or []):
        nm = normalize(affil)
        if nm and (nm in expected or expected in nm):
            return True
        # short-form match for well-known abbreviations
        for kw in ("oxford","cambridge","mit","cmu","stanford","berkeley","ethz",
                   "epfl","cornell","ucla","princeton","harvard","caltech","nvidia",
                   "google","microsoft","meta","adobe","apple","tencent","bytedance",
                   "alibaba","tsinghua","peking","pku","sjtu","ustc"):
            if kw in nm and kw in expected:
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    conf = cfg["conference"].lower() + str(cfg["year"])

    s2_cfg = cfg.get("s2", {}) or {}
    api_key = s2_cfg.get("api_key") or os.environ.get("S2_API_KEY")
    sleep_s = s2_cfg.get("sleep_seconds", 0.05 if api_key else 1.0)

    session = make_session(api_key)
    print(f"[enrich_s2] API key: {'configured' if api_key else 'NONE (unauthenticated, will rate-limit at 1 req/sec)'}")

    df = pd.read_csv(os.path.join(out_dir, f"{conf}_filtered.csv"))
    df["affiliation"] = df["affiliation"].fillna("")
    print(f"  {len(df)} filtered authors")

    if "ror_sector" in df.columns:
        df["sector"] = df["ror_sector"].fillna("").where(
            df["ror_sector"].fillna("") != "",
            df["affiliation"].apply(classify_sector))
    else:
        df["sector"] = df["affiliation"].apply(classify_sector)

    works, h_idx, sen = [None]*len(df), [None]*len(df), [""]*len(df)
    ids, hp = [""]*len(df), [""]*len(df)
    confidence = [""]*len(df)

    for i, (_, row) in enumerate(df.iterrows()):
        cands = s2_author_search(session, row["author_name"])
        time.sleep(sleep_s)
        if not cands: continue
        picked = next((c for c in cands if affil_matches(c, row["affiliation"])), None)
        if picked:
            conf_label = "high"
        elif len(cands) == 1:
            picked = cands[0]; conf_label = "medium"
        else:
            picked = cands[0]; conf_label = "low"
        works[i] = picked.get("paperCount") or 0
        h_idx[i] = picked.get("hIndex") or 0
        sen[i] = seniority_bucket(works[i], h_idx[i])
        # Reuse the same column name (openalex_id) so downstream views don't have to branch;
        # store the S2 author URL (which is human-clickable, matches the column's intent)
        ids[i] = picked.get("url") or f"https://www.semanticscholar.org/author/{picked.get('authorId','')}"
        hp[i] = picked.get("homepage") or ""
        confidence[i] = conf_label
        if (i + 1) % 50 == 0:
            print(f"    {i+1}/{len(df)}")

    df["openalex_id"] = ids   # column name kept for compatibility; value is S2 URL
    df["works_count"] = works
    df["h_index"] = h_idx
    df["seniority"] = sen
    df["homepage"] = hp
    df["openalex_confidence"] = confidence

    df = df.sort_values(["n_matched_papers", "h_index"],
                        ascending=[False, False], na_position="last")
    df.to_csv(os.path.join(out_dir, f"{conf}_shortlist.csv"), index=False)
    print(f"\n  saved {len(df)} → {conf}_shortlist.csv")
    print(f"  with h_index: {df.h_index.notna().sum()}")
    print(f"\n  sector breakdown:")
    print(df.sector.value_counts().to_string())
    print(f"\n  seniority breakdown:")
    print(df[df.seniority != ""].seniority.value_counts().to_string())
    print(f"\n  S2 disambiguation confidence:")
    print(df.openalex_confidence.value_counts().to_string())


if __name__ == "__main__":
    main()

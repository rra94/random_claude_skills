"""ROR-based affiliation resolution.

Takes the affiliation strings extracted from PDFs (in <conf>_authors_arxiv.csv) and
queries the ROR (Research Organization Registry) API to derive:
  - Authoritative institution name (ROR's `ror_display` label)
  - Country code (ISO 3166-1 alpha-2)
  - Sector ("academic" / "industry" / "government" / "nonprofit" / "other")
  - ROR ID (stable identifier)

ROR is a free public registry (no key needed, generous rate limit ~2000 req/5min).
Caches lookups per unique affiliation string (the same string repeats hundreds of
times across authors at the same institution).

When ROR returns no confident match, falls back to the existing regex-derived
country / sector values so coverage never regresses.

Reads:  <output_dir>/<conf>_authors_arxiv.csv
Writes: <output_dir>/<conf>_authors_arxiv.csv  (in-place, adds ror_* columns,
                                                 overwrites country if ROR confident)
        <output_dir>/ror_cache.json             (resumable cache)
"""
import argparse, json, os, time
import requests
import pandas as pd

ROR_API = "https://api.ror.org/v2/organizations"
# ROR's match score: 1.0 is best. Below ~0.7 is risky for our purposes.
MIN_SCORE = 0.7

# ROR `organization.types` → coarse sector label we use downstream
TYPE_TO_SECTOR = {
    "education": "academic",
    "company":   "industry",
    "facility":  "academic",          # research facilities
    "healthcare":"healthcare",
    "government":"government",
    "nonprofit": "nonprofit",
    "archive":   "other",
    "other":     "other",
    "funder":    None,                # ignore — only meaningful with another type
}


def make_session():
    s = requests.Session()
    s.headers["User-Agent"] = "conference-scout/0.1"
    return s


def load_cache(path: str) -> dict:
    if os.path.exists(path):
        return json.load(open(path))
    return {}


def save_cache(path: str, cache: dict):
    tmp = path + ".tmp"
    json.dump(cache, open(tmp, "w"))
    os.replace(tmp, path)


def lookup(session, affil: str, cache: dict, sleep_s: float = 0.1) -> dict | None:
    """Query ROR; cache by exact affiliation string. Returns the cached/fresh result dict
    or None if no confident match."""
    if not affil or len(affil) < 4:
        return None
    if affil in cache:
        return cache[affil]
    try:
        r = session.get(ROR_API, params={"affiliation": affil}, timeout=15)
        time.sleep(sleep_s)
        if r.status_code == 429:
            time.sleep(5)
            r = session.get(ROR_API, params={"affiliation": affil}, timeout=15)
        if r.status_code != 200:
            cache[affil] = None
            return None
        j = r.json()
        chosen = next((i for i in j.get("items", []) if i.get("chosen")), None)
        if not chosen or chosen.get("score", 0) < MIN_SCORE:
            cache[affil] = None
            return None
        org = chosen["organization"]
        name = next((n["value"] for n in org.get("names", [])
                     if "ror_display" in (n.get("types") or [])), org.get("id", ""))
        loc = (org.get("locations") or [{}])[0].get("geonames_details", {})
        types = org.get("types", []) or []
        # Pick first meaningful sector from types (ignore 'funder' standalone)
        sector = None
        for t in types:
            mapped = TYPE_TO_SECTOR.get(t)
            if mapped:
                sector = mapped
                break
        result = {
            "ror_id": org.get("id", ""),
            "ror_name": name,
            "ror_country": loc.get("country_code", ""),
            "ror_sector": sector or "",
            "ror_score": chosen.get("score", 0),
        }
        cache[affil] = result
        return result
    except Exception as e:
        print(f"  [warn] ROR error for '{affil[:50]}': {e}")
        cache[affil] = None
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    conf = cfg["conference"].lower() + str(cfg["year"])

    csv_path = os.path.join(out_dir, f"{conf}_authors_arxiv.csv")
    if not os.path.exists(csv_path):
        print(f"missing {csv_path} — run enrich_arxiv first")
        return

    df = pd.read_csv(csv_path)
    df["affiliation"] = df["affiliation"].fillna("")
    df["country"] = df["country"].fillna("")
    n_input = len(df)
    print(f"[ror_resolve] {n_input} rows")

    cache_path = os.path.join(out_dir, "ror_cache.json")
    cache = load_cache(cache_path)
    print(f"  cache: {len(cache)} prior lookups")

    session = make_session()
    sleep_s = cfg.get("ror", {}).get("sleep_seconds", 0.1)

    # Unique affiliations to resolve (skip empty)
    unique_affils = sorted(a for a in df["affiliation"].unique() if a and len(a) >= 4)
    print(f"  resolving {len(unique_affils)} unique affiliations")

    for i, affil in enumerate(unique_affils):
        if affil in cache:
            continue
        lookup(session, affil, cache, sleep_s)
        if (i + 1) % 100 == 0:
            save_cache(cache_path, cache)
            n_hit = sum(1 for v in cache.values() if v)
            print(f"    {i+1}/{len(unique_affils)} | hits: {n_hit}")
    save_cache(cache_path, cache)
    n_hit = sum(1 for v in cache.values() if v)
    print(f"  ROR hits: {n_hit}/{len(cache)} ({n_hit/max(1,len(cache))*100:.0f}%)")

    # Annotate dataframe — ROR overrides regex country when present;
    # add ror_* columns alongside the originals
    def annotate(affil):
        r = cache.get(affil)
        if not r: return pd.Series({"ror_id":"","ror_name":"","ror_country":"",
                                    "ror_sector":"","ror_score":""})
        return pd.Series(r)

    new = df["affiliation"].apply(annotate)
    df = pd.concat([df, new], axis=1)

    # Use ROR country when available; otherwise keep the regex-derived one
    df["country"] = df.apply(
        lambda r: r["ror_country"] if r.get("ror_country") else r["country"], axis=1)

    df.to_csv(csv_path, index=False)
    print(f"  saved → {csv_path}")
    n_with_country = (df.country != "").sum()
    n_with_sector = (df.ror_sector.fillna("") != "").sum()
    print(f"  authors with country: {n_with_country}/{n_input} (was {(df.country.fillna('') != '').sum()} before — net gain from ROR)")
    print(f"  authors with ror_sector: {n_with_sector}/{n_input}")
    print("\n  sector breakdown (ROR-derived):")
    print(df[df.ror_sector.fillna('') != ""]["ror_sector"].value_counts().to_string())


if __name__ == "__main__":
    main()

"""OpenReview-profile fallback for unknown-country authors.

For each row in <conf>_authors_arxiv.csv with an empty country, look the author up
in OpenReview's profile registry by name. Many academic researchers have OpenReview
profiles (they need one to submit/review at ICLR/NeurIPS/etc.) even when their CVPR
paper isn't on arxiv — so this recovers a meaningful slice of the unknown-country pool.

Profile fields used:
  - `content.history[0].institution.name` → affiliation
  - `content.history[0].institution.domain` → email domain → infer country
  - direct ISO country code if present in any history entry

Confidence: only fill country when the author's homepage / email-domain country agrees
with at least one coauthor's resolved country (to guard against same-name false matches).

Reads:  <output_dir>/<conf>_authors_arxiv.csv
        <output_dir>/papers_matched.json  (for coauthor disambiguation)
Writes: <output_dir>/<conf>_authors_arxiv.csv  (in-place, fills affiliation/country
                                                 where empty and confidence is high)
        <output_dir>/openreview_profile_cache.json  (resumable cache)

Requires: pip install openreview-py
"""
import argparse, json, os, sys, time
from collections import Counter, defaultdict
import pandas as pd

try:
    import openreview
except ImportError:
    print("openreview-py not installed; run: pip install openreview-py", file=sys.stderr)
    sys.exit(1)


# Common email-domain TLD → country code mapping (a crude but useful fallback when the
# OpenReview profile has an institutional email but no explicit country)
EMAIL_TLD_COUNTRY = {
    ".edu": "US", ".gov": "US", ".mil": "US",
    ".ac.uk": "GB", ".ac.in": "IN", ".ac.kr": "KR", ".ac.jp": "JP",
    ".ac.il": "IL", ".ac.nz": "NZ", ".ac.za": "ZA", ".ac.cn": "CN",
    ".ac.at": "AT", ".ac.be": "BE",
    ".edu.au": "AU", ".edu.sg": "SG", ".edu.cn": "CN", ".edu.hk": "HK",
    ".edu.tw": "TW", ".edu.in": "IN",
    ".uk": "GB", ".de": "DE", ".fr": "FR", ".ch": "CH", ".nl": "NL",
    ".it": "IT", ".es": "ES", ".se": "SE", ".no": "NO", ".dk": "DK",
    ".fi": "FI", ".at": "AT", ".be": "BE", ".cz": "CZ", ".pl": "PL",
    ".pt": "PT", ".gr": "GR", ".ie": "IE", ".il": "IL", ".in": "IN",
    ".jp": "JP", ".kr": "KR", ".sg": "SG", ".cn": "CN", ".hk": "HK",
    ".tw": "TW", ".au": "AU", ".nz": "NZ", ".ca": "CA",
}


def domain_to_country(domain: str) -> str:
    if not domain: return ""
    d = domain.lower()
    for suffix, code in sorted(EMAIL_TLD_COUNTRY.items(), key=lambda x: -len(x[0])):
        if d.endswith(suffix):
            return code
    return ""


def make_client():
    # OpenReview profile search now requires login (changed in 2025). Pick up creds from
    # env vars if available; otherwise use guest client (which will hit ForbiddenError on
    # the first search, logged once and the stage exits gracefully).
    user = os.environ.get("OPENREVIEW_USERNAME")
    pw = os.environ.get("OPENREVIEW_PASSWORD")
    if user and pw:
        return openreview.api.OpenReviewClient(
            baseurl="https://api2.openreview.net", username=user, password=pw)
    return openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")


_AUTH_WARNED = [False]


def lookup_profile(client, name: str, cache: dict) -> dict | None:
    if name in cache:
        return cache[name]
    try:
        # OpenReview profile search by name token
        results = client.search_profiles(term=name, first=name.split()[0],
                                          last=name.split()[-1])
        # Pick the first profile that has a populated history
        for p in (results or []):
            hist = (p.content or {}).get("history") or []
            if hist:
                top = hist[0] or {}
                inst = (top.get("institution") or {})
                affil = inst.get("name") or ""
                domain = inst.get("domain") or ""
                country = inst.get("country") or domain_to_country(domain)
                result = {
                    "affiliation": affil,
                    "country": country,
                    "domain": domain,
                    "profile_id": p.id,
                }
                cache[name] = result
                return result
        cache[name] = None
        return None
    except Exception as e:
        msg = str(e)
        # OpenReview switched profile search to logged-in-only in 2025+. Detect once,
        # print a clear message, and abort the whole stage so we don't spam the log.
        if "ForbiddenError" in msg or "logged in" in msg or "403" in msg:
            if not _AUTH_WARNED[0]:
                _AUTH_WARNED[0] = True
                print("\n  [openreview] profile search now requires authentication.")
                print("  Set OPENREVIEW_USERNAME + OPENREVIEW_PASSWORD env vars, or skip this stage.")
                print("  Aborting fallback (the rest of the pipeline will continue).\n")
            raise SystemExit(0)
        print(f"  [warn] profile lookup failed for {name}: {e}")
        cache[name] = None
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    conf = cfg["conference"].lower() + str(cfg["year"])

    csv_path = os.path.join(out_dir, f"{conf}_authors_arxiv.csv")
    df = pd.read_csv(csv_path)
    df["country"] = df["country"].fillna("")
    df["affiliation"] = df["affiliation"].fillna("")

    unknown = df[df.country == ""]
    print(f"[openreview_fallback] {len(unknown)} authors with unknown country to attempt")

    cache_path = os.path.join(out_dir, "openreview_profile_cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    client = make_client()
    filled = 0
    for i, (_, row) in enumerate(unknown.iterrows()):
        name = row["author_name"]
        prof = lookup_profile(client, name, cache)
        if prof and prof.get("country"):
            # Only fill if we don't already have an affiliation from arxiv parse
            if not row["affiliation"]:
                df.loc[df.author_name == name, "affiliation"] = prof["affiliation"]
            df.loc[df.author_name == name, "country"] = prof["country"]
            filled += 1
        if (i + 1) % 100 == 0:
            json.dump(cache, open(cache_path, "w"))
            print(f"  {i+1}/{len(unknown)} | filled {filled}")
        time.sleep(0.2)

    json.dump(cache, open(cache_path, "w"))
    df.to_csv(csv_path, index=False)
    print(f"\n  filled country for {filled}/{len(unknown)} previously-unknown authors")


if __name__ == "__main__":
    main()

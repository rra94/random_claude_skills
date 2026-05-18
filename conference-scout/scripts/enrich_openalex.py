"""Add sector (academic/industry) and seniority via OpenAlex author search.

Reads <conf>_filtered.csv.
For each author, search OpenAlex authors by name. Disambiguate by matching candidate
institutions against the arxiv-derived affiliation. Pull works_count, h_index, homepage_url.
Bucket into seniority labels. Regex-classify sector from affiliation string.

Writes <conf>_shortlist.csv (filtered + sector/seniority/h_index/works/openalex_id/homepage).
"""
import argparse, json, os, re, time
from urllib.parse import quote_plus

import requests
import pandas as pd

INDUSTRY_KW = re.compile(
    r"\b(Google|DeepMind|Alphabet|YouTube|Waymo|Meta|Facebook|FAIR|Instagram|"
    r"Microsoft|MSR|GitHub|Azure|NVIDIA|Apple|Amazon|AWS|Adobe|OpenAI|Anthropic|xAI|"
    r"IBM|Salesforce|Disney|Sony|Samsung|Bosch|Toyota|Cruise|Zoox|Aurora|Argo|Nuro|"
    r"Wayve|Tesla|Pony\.ai|Motional|Mobileye|Qualcomm|Intel|Tencent|Alibaba|Bytedance|"
    r"Huawei|Baidu|Xiaomi|DAMO|Snap|Pinterest|Roblox|Unity|Epic Games|Honda|"
    r"Applied Intuition|Helm\.ai|Recursion|insitro|Genentech|Roche|Novartis|"
    r"Inc\.|Corp\.|Ltd\.|GmbH|Research Lab)\b", re.I)
ACADEMIC_KW = re.compile(
    r"\b(University|Universit|Institute|Institut|College|School|Polytechnic|Politecnico|"
    r"Academia|Max Planck|CNRS|INRIA|CSAIL|ETH|EPFL|KAIST|HKUST|HKU|CUHK|IIT|IISc|TUM|"
    r"UCL|MIT|CMU)\b", re.I)


def classify_sector(affil: str) -> str:
    if not affil: return ""
    i = bool(INDUSTRY_KW.search(affil))
    a = bool(ACADEMIC_KW.search(affil))
    if i and not a: return "industry"
    if a and not i: return "academic"
    if i and a:     return "industry+academic"
    return "unknown"


def normalize(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def oa_authors(session, name: str, mailto: str):
    try:
        r = session.get("https://api.openalex.org/authors",
                        params={"search": name, "per-page": 5, "mailto": mailto},
                        timeout=15)
        if r.status_code == 200:
            return r.json().get("results", [])
    except Exception:
        pass
    return []


def affil_matches(cand, expected_affil: str) -> bool:
    expected = normalize(expected_affil)
    if not expected: return False
    insts = cand.get("last_known_institutions") or []
    for inst in insts:
        nm = normalize(inst.get("display_name", ""))
        if nm and (nm in expected or expected in nm): return True
        for kw in ("oxford","cambridge","mit","cmu","stanford","berkeley","ethz",
                   "epfl","cornell","ucla","princeton","harvard","caltech","nvidia",
                   "google","microsoft","meta","adobe","apple","tencent","bytedance",
                   "alibaba","tsinghua","peking","pku","sjtu","ustc"):
            if kw in nm and kw in expected: return True
    for a in (cand.get("affiliations") or [])[:10]:
        nm = normalize(a.get("institution", {}).get("display_name", ""))
        if nm and (nm in expected or expected in nm): return True
    return False


def seniority_bucket(wc, hi):
    w, h = wc or 0, hi or 0
    if w >= 80 or h >= 30: return "Senior (Faculty/Principal)"
    if w >= 30 or h >= 15: return "Mid (Postdoc/Sr.Researcher)"
    if w >= 5:             return "Junior (Late PhD/Early career)"
    if w >= 1:             return "Junior (PhD student?)"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    conf = cfg["conference"].lower() + str(cfg["year"])
    mailto = cfg.get("openalex", {}).get("mailto", "you@example.com")
    sleep_s = cfg.get("openalex", {}).get("sleep_seconds", 0.12)

    session = requests.Session()
    session.headers["User-Agent"] = f"conference-scout/0.1 (mailto:{mailto})"

    df = pd.read_csv(os.path.join(out_dir, f"{conf}_filtered.csv"))
    df["affiliation"] = df["affiliation"].fillna("")
    print(f"[enrich_openalex] {len(df)} filtered authors")

    df["sector"] = df["affiliation"].apply(classify_sector)

    works, h_idx, sen, ids, hp = [None]*len(df), [None]*len(df), [""]*len(df), [""]*len(df), [""]*len(df)
    print("  fetching OpenAlex records…")
    for i, (_, row) in enumerate(df.iterrows()):
        cands = oa_authors(session, row["author_name"], mailto)
        time.sleep(sleep_s)
        if not cands: continue
        picked = next((c for c in cands if affil_matches(c, row["affiliation"])), None)
        if not picked and len(cands) == 1: picked = cands[0]
        if not picked: picked = cands[0]
        wc = picked.get("works_count") or 0
        hh = (picked.get("summary_stats") or {}).get("h_index") or 0
        works[i] = wc; h_idx[i] = hh; sen[i] = seniority_bucket(wc, hh)
        ids[i] = picked.get("id", ""); hp[i] = picked.get("homepage_url") or ""
        if (i+1) % 50 == 0: print(f"    {i+1}/{len(df)}")

    df["openalex_id"] = ids
    df["works_count"] = works
    df["h_index"] = h_idx
    df["seniority"] = sen
    df["homepage"] = hp

    df = df.sort_values(["n_matched_papers","h_index"],
                        ascending=[False, False], na_position="last")
    df.to_csv(os.path.join(out_dir, f"{conf}_shortlist.csv"), index=False)
    print(f"  saved {len(df)} → {conf}_shortlist.csv")
    print(f"\n  sector breakdown:")
    print(df.sector.value_counts().to_string())
    print(f"\n  seniority breakdown:")
    print(df[df.seniority != ""].seniority.value_counts().to_string())


if __name__ == "__main__":
    main()

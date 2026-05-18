"""Filter authors_arxiv.csv to a country keep-list.

Reads <conf>_authors_arxiv.csv + config.filter.keep_countries.
Writes <conf>_filtered.csv (kept) and <conf>_unknown_country.csv (no country).
"""
import argparse, json, os
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    out_dir = cfg["output_dir"]
    conf = cfg["conference"].lower() + str(cfg["year"])
    keep = set(cfg["filter"]["keep_countries"])

    df = pd.read_csv(os.path.join(out_dir, f"{conf}_authors_arxiv.csv"))
    df["country"] = df["country"].fillna("")
    df["affiliation"] = df["affiliation"].fillna("")
    print(f"[filter] {len(df)} enriched authors")

    kept = df[df.country.isin(keep)].sort_values("n_matched_papers", ascending=False)
    excluded = df[(df.country != "") & ~df.country.isin(keep)]
    unknown = df[df.country == ""]

    kept.to_csv(os.path.join(out_dir, f"{conf}_filtered.csv"), index=False)
    unknown.to_csv(os.path.join(out_dir, f"{conf}_unknown_country.csv"), index=False)

    print(f"  kept:     {len(kept)}")
    print(f"  excluded: {len(excluded)}  (top: {excluded.country.value_counts().head(8).to_dict()})")
    print(f"  unknown:  {len(unknown)}")
    print(f"\n  kept-list breakdown:")
    print(kept.country.value_counts().head(20).to_string())


if __name__ == "__main__":
    main()

"""Orchestrator — run all stages of the conference-scout pipeline.

Usage:
    python3 pipeline.py --config my_config.json
    python3 pipeline.py --config my_config.json --skip scrape,classify
    python3 pipeline.py --config my_config.json --only enrich_arxiv

Stage order: scrape → classify → enrich_arxiv → filter → enrich_openalex → format.
Each stage is idempotent — re-running won't redo work that's already cached.
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

STAGES = [
    ("scrape",          "scrape"),           # picks scrape_cvf or scrape_openreview from config
    ("classify",        "classify.py"),
    ("enrich_arxiv",    "enrich_arxiv.py"),
    ("ror_resolve",     "ror_resolve.py"),   # ROR-based country + sector; cached
    ("filter",          "filter_countries.py"),
    ("enrich_openalex", "enrich_openalex.py"),
    ("format",          "format_output.py"),
]


def run_stage(label: str, script: str, config_path: str) -> bool:
    here = Path(__file__).resolve().parent
    if label == "scrape":
        cfg = json.load(open(config_path))
        source = cfg["scrape"]["source"]
        script = f"scrape_{source}.py"
    script_path = here / script
    if not script_path.exists():
        print(f"[pipeline] missing: {script_path}", file=sys.stderr)
        return False
    print(f"\n{'='*60}\n[pipeline] {label}: python3 {script_path.name}\n{'='*60}")
    t0 = time.time()
    rc = subprocess.call([sys.executable, str(script_path), "--config", config_path])
    elapsed = time.time() - t0
    print(f"\n[pipeline] {label} {'OK' if rc==0 else 'FAILED'} in {elapsed:.1f}s")
    return rc == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--skip", help="comma-separated stage names to skip")
    ap.add_argument("--only", help="comma-separated stage names to run (others skipped)")
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print(f"config not found: {args.config}", file=sys.stderr); sys.exit(1)
    cfg = json.load(open(args.config))
    os.makedirs(cfg["output_dir"], exist_ok=True)

    skip = set((args.skip or "").split(",")) if args.skip else set()
    only = set((args.only or "").split(",")) if args.only else None

    for label, script in STAGES:
        if only and label not in only: continue
        if label in skip:
            print(f"[pipeline] {label}: skipped"); continue
        ok = run_stage(label, script, args.config)
        if not ok:
            print(f"[pipeline] aborting at {label}", file=sys.stderr); sys.exit(1)

    print("\n[pipeline] done. Outputs in", cfg["output_dir"])


if __name__ == "__main__":
    main()

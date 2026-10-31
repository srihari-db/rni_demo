"""Generate the deterministic synthetic RNI dataset and validate it before anything is published.

Usage (Databricks job or locally):
    python scripts/generate_rni_data.py --catalog rni_demo                 # writes to /Volumes/<catalog>/bronze/landing/current
    python scripts/generate_rni_data.py --output /tmp/rni_out --no-spark   # local Parquet only

The run FAILS (non-zero exit) if any referential-integrity, ledger-reconciliation, lifecycle, returns or scenario
check fails, so invalid data is never loaded. A JSON summary (row counts, date ranges, checks) is written next to
the Parquet extracts.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

def _repo_root():
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # serverless spark_python_task does not define __file__
        if "--root" in sys.argv:
            return Path(sys.argv[sys.argv.index("--root") + 1])
        return Path.cwd()


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))

from src.common import runtime  # noqa: E402
from src.data import quality  # noqa: E402
from src.data.simulator import SIMULATOR_VERSION, simulate  # noqa: E402


def main(argv=None):
    runtime.setup_logging()
    p = runtime.base_args("Generate synthetic RNI data")
    p.add_argument("--output", default=None, help="Output directory (default: UC volume landing/current)")
    p.add_argument("--no-spark", action="store_true", help="Do not create schemas/volume (local runs)")
    args = p.parse_args(argv)

    cfg = runtime.load_yaml(args.config)
    out = Path(args.output or f"/Volumes/{args.catalog}/bronze/landing/current")
    if not args.no_spark:
        spark = runtime.get_spark()
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {args.catalog}.bronze")
        spark.sql(f"CREATE VOLUME IF NOT EXISTS {args.catalog}.bronze.landing")

    tables = simulate(cfg)
    results = quality.run_all(tables, cfg)
    failed = [r for r in results if not r.passed]
    summary = dict(
        simulator_version=SIMULATOR_VERSION, seed=cfg["simulation"]["seed"],
        start_date=cfg["simulation"]["start_date"], snapshot_date=cfg["simulation"]["snapshot_date"],
        config_sha256=hashlib.sha256(Path(args.config).read_bytes()).hexdigest(),
        tables=quality.summarize(tables), checks=[r.as_dict() for r in results],
        checks_passed=len(results) - len(failed), checks_failed=len(failed),
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "checks"}, indent=2, default=str))
    for r in results:
        print(("PASS " if r.passed else "FAIL ") + r.name + " | " + r.detail[:200])
    if failed:
        raise SystemExit(f"{len(failed)} data-quality checks failed; nothing written.")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        d = out / name
        d.mkdir(parents=True, exist_ok=True)
        df.to_parquet(d / "part-00000.parquet", index=False, coerce_timestamps="us", allow_truncated_timestamps=True)
    (out / "_generation_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"Wrote {len(tables)} tables to {out}")
    return summary


if __name__ == "__main__":
    main()

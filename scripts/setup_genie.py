"""Create or update the 'RNI Inventory Intelligence Agent' Genie space.

1. Executes every verified example SQL on the warehouse (fails if any errors or returns no rows).
2. Creates the space (or updates it if --space-id is given / a space with the same title exists).
3. Asks every benchmark question through the Genie Conversation API and records whether Genie answered and
   whether its result matches the verified SQL result (docs/genie_validation.md + JSON).

Usage: python scripts/setup_genie.py --warehouse-id <id> [--catalog rni_demo] [--space-id <id>] [--skip-benchmarks]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common.sqlexec import run  # noqa: E402
from src.genie.client import GenieClient  # noqa: E402
from src.genie.space_config import EXAMPLE_SQL, SPACE_DESCRIPTION, SPACE_TITLE, serialized_space  # noqa: E402


def _num_signature(df):
    import pandas as pd
    vals = []
    for c in df.columns:
        v = pd.to_numeric(df[c], errors="coerce")
        if v.notna().any():
            vals.append(round(float(v.fillna(0).sum()), 0))
    return sorted(vals)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", default="rni_demo")
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--space-id", default=None)
    p.add_argument("--skip-benchmarks", action="store_true")
    a = p.parse_args()
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    g = f"{a.catalog}.gold"

    verified = {}
    for q, sql in EXAMPLE_SQL:
        df = run(w, a.warehouse_id, sql.format(g=g))
        assert len(df) > 0, f"verified SQL returned no rows: {q}"
        verified[q] = df
        print(f"verified ({len(df)} rows): {q}")

    space = json.dumps(serialized_space(a.catalog))
    space_id = a.space_id
    if not space_id:
        for s in w.genie.list_spaces().spaces or []:
            if s.title == SPACE_TITLE:
                space_id = s.space_id
    if space_id:
        w.genie.update_space(space_id, serialized_space=space, title=SPACE_TITLE, description=SPACE_DESCRIPTION,
                             warehouse_id=a.warehouse_id)
        print("updated space", space_id)
    else:
        sp = w.genie.create_space(a.warehouse_id, space, title=SPACE_TITLE, description=SPACE_DESCRIPTION)
        space_id = sp.space_id
        print("created space", space_id)
    (ROOT / "config" / "genie_space_id.txt").write_text(space_id + "\n")

    results = []
    if not a.skip_benchmarks:
        gc = GenieClient(space_id, w, timeout_s=180)
        for q, _ in EXAMPLE_SQL:
            ans = gc.ask(q)
            ok_src = ans.source == "GENIE"
            match = None
            if ok_src and ans.data is not None and len(ans.data):
                match = bool(set(_num_signature(ans.data)) & set(_num_signature(verified[q])))
            results.append(dict(question=q, genie_answered=ok_src, rows=None if ans.data is None else len(ans.data),
                                matches_verified_sql=match, elapsed_s=round(ans.elapsed_s, 1), genie_sql=ans.sql,
                                error=ans.error))
            print(json.dumps(results[-1])[:300])
            time.sleep(2)
        (ROOT / "docs" / "genie_benchmark_results.json").write_text(json.dumps(results, indent=2))
    print("SPACE_ID", space_id)


if __name__ == "__main__":
    main()

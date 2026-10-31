"""Create Unity Catalog tables and load the synthetic extracts: landing Parquet -> bronze -> silver.

* Executes sql/create_rni_tables.sql (schemas, volume, silver + ml tables with comments and constraints).
* Refuses to replace any existing table that is not marked TBLPROPERTIES ('rni_demo.managed'='true').
* bronze.<table> = raw extract + ingestion metadata (_ingested_at, _source_system, _batch_id).
* silver.<table> = typed copy conforming to the DDL; Delta CHECK constraints enforce non-negative inventory etc.
"""
from __future__ import annotations

import json
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

SILVER = ["customer_master", "product_master", "rni_devices", "customer_product_assignments", "par_levels",
          "dosing_rules", "lot_master", "usage_history", "stockout_events", "shipment_orders",
          "shipment_lot_allocations", "return_orders", "return_order_links", "inventory_events",
          "inventory_positions", "scenario_registry", "device_telemetry"]


def main(argv=None):
    runtime.setup_logging()
    p = runtime.base_args("Load synthetic RNI data into Unity Catalog")
    p.add_argument("--landing", default=None)
    args = p.parse_args(argv)
    cat = args.catalog
    landing = args.landing or f"/Volumes/{cat}/bronze/landing/current"
    spark = runtime.get_spark()

    n = runtime.run_sql_file(spark, str(runtime.repo_root() / "sql" / "create_rni_tables.sql"), cat)
    print(f"Executed {n} DDL statements")
    summary = json.loads(Path(landing, "_generation_summary.json").read_text())
    batch = f"seed{summary['seed']}-{summary['config_sha256'][:12]}"

    bronze_tables = [f"{cat}.bronze.{t}" for t in SILVER + ["simulation_ground_truth"]]
    runtime.guard_managed(spark, bronze_tables)
    counts = {}
    for t in SILVER + ["simulation_ground_truth"]:
        src = runtime.SOURCE_SYSTEM.get(t, "SIM")
        spark.sql(f"""
            CREATE OR REPLACE TABLE {cat}.bronze.{t}
            COMMENT 'Raw synthetic extract ({src}). Not for direct consumption; use silver/gold.'
            TBLPROPERTIES ('{runtime.MANAGED_PROP}'='true')
            AS SELECT *, current_timestamp() AS _ingested_at, '{src}' AS _source_system, '{batch}' AS _batch_id
            FROM parquet.`{landing}/{t}`""")
    for t in SILVER:
        target = f"{cat}.silver.{t}"
        cols = spark.table(target).schema
        sel = ", ".join(f"CAST(`{f.name}` AS {f.dataType.simpleString()}) AS `{f.name}`" for f in cols.fields)
        spark.sql(f"INSERT OVERWRITE {target} SELECT {sel} FROM {cat}.bronze.{t}")
        counts[t] = spark.table(target).count()
        expected = summary["tables"][t]["rows"]
        if counts[t] != expected:
            raise RuntimeError(f"{target}: loaded {counts[t]} rows, generator produced {expected}")
    gt = spark.table(f"{cat}.ml.simulation_ground_truth").schema
    sel = ", ".join(f"CAST(`{f.name}` AS {f.dataType.simpleString()}) AS `{f.name}`" for f in gt.fields)
    spark.sql(f"INSERT OVERWRITE {cat}.ml.simulation_ground_truth SELECT {sel} FROM {cat}.bronze.simulation_ground_truth")
    print(json.dumps(counts, indent=2))
    return counts


if __name__ == "__main__":
    main()

"""Create the Gold views / KPI table (sql/create_gold_views.sql) and the Unity Catalog metric view, score IoT
telemetry, and print the executive KPI row."""
from __future__ import annotations

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
from src.iot.anomaly import score  # noqa: E402

METRIC_VIEW_YAML = """
version: 0.1
source: {cat}.gold.inventory_exposure_current
dimensions:
  - name: Region
    expr: region
  - name: Customer
    expr: customer_name
  - name: Customer Type
    expr: customer_type
  - name: Product Category
    expr: product_category
  - name: Product
    expr: product_name
  - name: Critical Stock
    expr: critical_stock_flag
  - name: Stock Status
    expr: stock_status
measures:
  - name: Inventory Value
    expr: SUM(inventory_value)
  - name: Excess Value Above PAR
    expr: SUM(excess_value)
  - name: Near Expiry Value
    expr: SUM(near_expiry_value)
  - name: Healthy Value
    expr: SUM(healthy_value)
  - name: Units On Hand
    expr: SUM(on_hand_qty)
  - name: Excess Share
    expr: SUM(excess_value) / NULLIF(SUM(inventory_value), 0)
"""


def main(argv=None):
    runtime.setup_logging()
    args = runtime.base_args("Build RNI gold layer").parse_args(argv)
    cat = args.catalog
    spark = runtime.get_spark()

    tel = runtime.to_pandas(spark, f"{cat}.silver.device_telemetry")
    runtime.write_pandas(spark, score(tel), f"{cat}.ml.device_telemetry_scored")

    n = runtime.run_sql_file(spark, str(runtime.repo_root() / "sql" / "create_gold_views.sql"), cat)
    print(f"Executed {n} gold statements")
    try:
        spark.sql(f"""CREATE OR REPLACE VIEW {cat}.gold.mv_inventory_exposure
            WITH METRICS LANGUAGE YAML
            COMMENT 'Governed inventory exposure metrics (synthetic). Buckets are mutually exclusive.'
            AS $$ {METRIC_VIEW_YAML.format(cat=cat)} $$""")
        print("Metric view created: gold.mv_inventory_exposure")
    except Exception as e:  # metric views may be unavailable on some runtimes; views remain the source of truth
        print(f"WARNING metric view not created ({type(e).__name__}): {str(e)[:300]}")
    print(spark.table(f"{cat}.gold.kpi_executive").toPandas().T.to_string())


if __name__ == "__main__":
    main()

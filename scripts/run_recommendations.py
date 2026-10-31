"""Execute the replenishment decision engine for every pending shipment request and every customer/SKU
(cycle review) and persist the results to ml.replenishment_recommendations. Never fabricates results."""
from __future__ import annotations

import datetime as dt
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
from src.optimization.batch import run_batch  # noqa: E402
from src.optimization.engine import EngineRules  # noqa: E402

TABLES = ["inventory_positions", "shipment_orders", "return_orders", "usage_history", "par_levels",
          "product_master", "dosing_rules", "customer_product_assignments"]


def main(argv=None):
    runtime.setup_logging()
    args = runtime.base_args("Run RNI decision engine").parse_args(argv)
    cat = args.catalog
    cfg = runtime.load_yaml(args.config)
    rules = EngineRules.from_config(runtime.load_yaml(args.rules))
    snapshot = dt.date.fromisoformat(str(cfg["simulation"]["snapshot_date"]))
    spark = runtime.get_spark()
    t = {n: runtime.to_pandas(spark, f"{cat}.silver.{n}") for n in TABLES}
    t["inventory_positions"] = t["inventory_positions"][t["inventory_positions"].is_current == True]  # noqa: E712
    fc = runtime.to_pandas(spark, f"{cat}.ml.demand_forecasts", f"forecast_date = DATE'{snapshot}'")
    if fc.empty:
        raise SystemExit("No forecasts for the snapshot — run the forecasting task first.")
    recs = run_batch(t, fc, snapshot, rules, model_version=str(fc.model_version.iloc[0]))
    runtime.write_pandas(spark, recs, f"{cat}.ml.replenishment_recommendations")
    print(recs.groupby(["recommendation_type", "risk_category"]).size().to_string())
    print(recs[recs.scenario_id.notna() & (recs.recommendation_type == "SHIPMENT_REQUEST")][
        ["scenario_id", "requested_qty", "recommended_qty", "par_only_baseline_qty", "risk_category",
         "potential_exposure_value"]].to_string())


if __name__ == "__main__":
    main()

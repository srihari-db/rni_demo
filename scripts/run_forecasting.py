"""Execute the demand forecasting pipeline on silver.usage_history, track it in MLflow, register the model in
Unity Catalog and persist forecasts to ml.demand_forecasts / ml.demand_forecast_weekly.

Forecast rows are produced ONLY by executing src.forecasting.pipeline — never fabricated.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
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

import pandas as pd  # noqa: E402

from src.common import runtime  # noqa: E402
from src.forecasting import pipeline  # noqa: E402

EVAL_NOTES = """# Demand forecast evaluation notes (auto-generated)

* Rolling-origin backtest at {origins} days before the snapshot; horizons 30/60/90 days; models only see
  observations up to each origin (no future leakage).
* Models: 12-week moving average and 52-week average (baselines), SES, Croston-SBA, TSB (intermittent), and an
  adjusted seasonal-naive model. One model is selected per demand class by backtest MAE; a simpler model wins ties
  within 2%. The most complex model is not assumed to be best.
* Intervals: empirical bootstrap of recent weekly demand rescaled to the point forecast, widened by a
  split-conformal margin fitted on the backtest so empirical coverage is close to the nominal 80%.
* Limitations: rare/emergency demand (antivenoms, antidotes, reversal agents) has very few events; point forecasts
  for these series are near zero and are NOT a safe basis for stocking. The decision engine therefore never lets a
  forecast reduce stock below the approved mandatory minimum and raises critical targets to the largest observed
  single-week demand. WAPE is unstable for near-zero-demand classes, so selection uses MAE.
* Data are synthetic; accuracy figures describe the simulator, not FFF operations.

## Selection
{selection}
"""


class RNIDemandForecaster:  # defined lazily as an mlflow.pyfunc.PythonModel subclass in main()
    pass


def main(argv=None):
    runtime.setup_logging()
    p = runtime.base_args("Run RNI demand forecasting")
    p.add_argument("--experiment", default=None)
    p.add_argument("--register", default="true")
    args = p.parse_args(argv)
    cat = args.catalog
    cfg = runtime.load_yaml(args.config)
    snapshot = dt.date.fromisoformat(str(cfg["simulation"]["snapshot_date"]))
    spark = runtime.get_spark()

    import mlflow
    from mlflow.models import infer_signature

    usage = runtime.to_pandas(spark, f"{cat}.silver.usage_history", f"usage_date <= DATE'{snapshot}'")
    pairs = [tuple(x) for x in runtime.to_pandas(spark, f"{cat}.silver.customer_product_assignments")[["customer_id", "sku"]].values]
    pairs.sort()

    user = spark.sql("SELECT current_user() AS u").collect()[0].u
    exp_path = args.experiment or f"/Users/{user}/rni_demo_demand_forecasting"
    mlflow.set_experiment(exp_path)
    mlflow.set_registry_uri("databricks-uc")
    model_name = f"{cat}.ml.rni_demand_forecaster"

    with mlflow.start_run(run_name=f"rni-forecast-{snapshot}") as run:
        mlflow.log_params(dict(snapshot_date=str(snapshot), n_series=len(pairs), horizons="30,60,90",
                               backtest_origins_days=",".join(map(str, pipeline.BACKTEST_ORIGINS_DAYS)),
                               interval_level=pipeline.INTERVAL_LEVEL, pipeline_version=pipeline.PIPELINE_VERSION,
                               training_obs_max_date=str(pd.to_datetime(usage.usage_date).max().date()),
                               candidate_models=",".join(pipeline.M.MODELS)))
        bt = pipeline.backtest(usage, pairs, snapshot)
        metrics = pipeline.evaluate(bt)
        selection = pipeline.select_models(metrics, bt)
        for r in metrics.itertuples():
            key = f"{r.demand_class}.{r.model_name}.h{r.horizon_days}"
            for m in ("mae", "wape", "bias", "under_forecast_share", "interval_coverage"):
                v = getattr(r, m)
                if pd.notna(v):
                    mlflow.log_metric(f"{key}.{m}", float(v))
        for cls, s in selection.items():
            mlflow.log_metric(f"selected.{cls}.mae", s["mae"])
            mlflow.log_metric(f"selected.{cls}.mae_improvement_vs_baseline", s["mae_improvement_vs_baseline"])
            mlflow.set_tag(f"selected_model.{cls}", s["model_name"])

        with tempfile.TemporaryDirectory() as td:
            sel_path = Path(td) / "model_selection.json"
            sel_path.write_text(json.dumps(selection, indent=2, default=str))
            metrics.to_csv(Path(td) / "backtest_metrics.csv", index=False)
            bt.to_csv(Path(td) / "backtest_detail.csv", index=False)
            sel_md = "\n".join(f"* **{k}** → {v['model_name']} (MAE {v['mae']:.2f}, baseline {v['baseline_mae']:.2f}, "
                               f"improvement {v['mae_improvement_vs_baseline']:.0%}, raw interval coverage "
                               f"{v['interval_coverage']:.0%})" for k, v in selection.items())
            (Path(td) / "evaluation_notes.md").write_text(
                EVAL_NOTES.format(origins=pipeline.BACKTEST_ORIGINS_DAYS, selection=sel_md))
            mlflow.log_artifacts(td, artifact_path="evaluation")

            import mlflow.pyfunc

            class Forecaster(mlflow.pyfunc.PythonModel):
                """Input: long usage rows (customer_id, sku, usage_date, quantity_consumed) + as_of_date column.
                Output: 30/60/90-day forecasts with 80% intervals using the backtest-selected model per class."""

                def load_context(self, context):
                    self.selection = json.loads(Path(context.artifacts["selection"]).read_text())

                def predict(self, context, model_input, params=None):
                    from src.forecasting import pipeline as pl
                    df = model_input.copy()
                    as_of = pd.to_datetime(df["as_of_date"]).max().date()
                    prs = sorted({(a, b) for a, b in zip(df.customer_id, df.sku)})
                    fc, _ = pl.forecast(df, prs, as_of, self.selection, "pyfunc")
                    return fc[["customer_id", "sku", "forecast_horizon", "predicted_demand", "lower_bound", "upper_bound",
                               "model_name", "demand_class"]]

            ex = usage[usage.customer_id == pairs[0][0]].head(200).copy()
            ex["usage_date"] = pd.to_datetime(ex.usage_date).dt.strftime("%Y-%m-%d")
            ex["as_of_date"] = str(snapshot)
            ex = ex[["customer_id", "sku", "usage_date", "quantity_consumed", "as_of_date"]]
            mdl = Forecaster()
            mdl.selection = selection
            out_ex = mdl.predict(None, ex)
            info = mlflow.pyfunc.log_model(
                artifact_path="model", python_model=mdl, artifacts={"selection": str(sel_path)},
                code_paths=[str(runtime.repo_root() / "src")], signature=infer_signature(ex, out_ex),
                input_example=ex.head(5), pip_requirements=["pandas", "numpy"],
                registered_model_name=model_name if args.register == "true" else None)
        version = getattr(info, "registered_model_version", None)
        model_version = f"{model_name}/{version}" if version else f"runs:/{run.info.run_id}/model"
        mlflow.set_tag("model_version", model_version)

        fc, weekly = pipeline.forecast(usage, pairs, snapshot, selection, model_version)
        assert (pd.to_datetime(fc.training_obs_max_date) <= pd.to_datetime(fc.training_cutoff_date)).all()
        fc["mlflow_run_id"] = run.info.run_id
        weekly["mlflow_run_id"] = run.info.run_id
        runtime.write_pandas(spark, fc, f"{cat}.ml.demand_forecasts")
        runtime.write_pandas(spark, weekly, f"{cat}.ml.demand_forecast_weekly")
        m = metrics.copy()
        m["selected"] = [selection.get(c, {}).get("model_name") == n for c, n in zip(m.demand_class, m.model_name)]
        m["mlflow_run_id"] = run.info.run_id
        runtime.write_pandas(spark, m, f"{cat}.ml.forecast_backtest_metrics")
        mlflow.log_metric("forecast_rows", len(fc))
        print(json.dumps(dict(run_id=run.info.run_id, experiment=exp_path, model_version=model_version,
                              forecasts=len(fc), selection={k: v["model_name"] for k, v in selection.items()}), indent=2))


if __name__ == "__main__":
    main()

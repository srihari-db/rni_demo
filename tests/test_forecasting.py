"""Forecasting pipeline tests: chronological splits, leakage, model behaviour, intervals."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src.forecasting import models as M
from src.forecasting import pipeline


@pytest.fixture(scope="module")
def usage(tables):
    return tables["usage_history"]


@pytest.fixture(scope="module")
def pairs(tables):
    return sorted(map(tuple, tables["customer_product_assignments"][["customer_id", "sku"]].values))[:40]


def test_weekly_series_ignores_rows_after_cutoff(usage, pairs, snapshot):
    cutoff = snapshot - dt.timedelta(days=91)
    a = pipeline.weekly_series(usage, pairs, cutoff)
    future = usage.copy()
    future["usage_date"] = (pd.to_datetime(future.usage_date) + pd.Timedelta(days=400)).dt.date
    future = future[future.usage_date > cutoff]                 # strictly future observations only
    assert len(future) > 0
    b = pipeline.weekly_series(pd.concat([usage, future]), pairs, cutoff)
    for p in pairs:
        np.testing.assert_array_equal(a[p], b[p])


def test_forecast_unchanged_by_future_observations(usage, pairs, snapshot):
    sel = {c: {"model_name": "TSB", "conformal_margin": {}} for c in ["SMOOTH", "ERRATIC", "INTERMITTENT", "LUMPY", "NO_RECENT_DEMAND"]}
    as_of = snapshot - dt.timedelta(days=60)
    f1, _ = pipeline.forecast(usage, pairs, as_of, sel, "t")
    f2, _ = pipeline.forecast(usage[pd.to_datetime(usage.usage_date).dt.date <= as_of], pairs, as_of, sel, "t")
    pd.testing.assert_frame_equal(f1.reset_index(drop=True), f2.reset_index(drop=True))
    assert (pd.to_datetime(f1.training_obs_max_date).dt.date <= as_of).all()


def test_backtest_actuals_are_strictly_after_origin(usage, pairs, snapshot):
    bt = pipeline.backtest(usage, pairs[:10], snapshot)
    assert set(bt.origin_date) == {snapshot - dt.timedelta(days=d) for d in pipeline.BACKTEST_ORIGINS_DAYS}
    for (o, h), g in bt.groupby(["origin_date", "horizon_days"]):
        assert o + dt.timedelta(days=int(h)) <= snapshot          # evaluation window never passes the snapshot


def test_full_pipeline_outputs(usage, pairs, snapshot):
    res = pipeline.run(usage, pairs, snapshot)
    fc = res["forecasts"]
    assert set(fc.forecast_horizon) == {30, 60, 90}
    assert len(fc) == 3 * len(pairs)
    assert ((fc.lower_bound <= fc.predicted_demand + 1e-9) & (fc.predicted_demand <= fc.upper_bound + 1e-9)).all()
    assert (fc.lower_bound >= 0).all()
    g = fc.pivot_table(index=["customer_id", "sku"], columns="forecast_horizon", values="predicted_demand")
    assert ((g[30] <= g[60] + 1e-9) & (g[60] <= g[90] + 1e-9)).all()      # cumulative horizons are monotone
    for cls, s in res["selection"].items():
        assert s["model_name"] in M.MODELS
        assert s["mae"] <= s["baseline_mae"] + 1e-9                         # never worse than the baseline


def test_classification():
    assert M.classify_demand(np.array([5, 6, 5, 7, 6] * 20))["demand_class"] == "SMOOTH"
    assert M.classify_demand(np.array([0, 0, 0, 3, 0, 0, 0, 0, 1] * 10))["demand_class"] in ("INTERMITTENT", "LUMPY")
    assert M.classify_demand(np.zeros(52))["demand_class"] == "NO_RECENT_DEMAND"


def test_intermittent_models_decay_during_zero_runs():
    y = np.array([0] * 20 + [4] + [0] * 30, dtype=float)
    assert M.tsb(y, 1)[0] < M.tsb(y[:22], 1)[0]
    assert M.croston_sba(y, 1)[0] > 0


def test_bootstrap_interval_contains_point_and_is_reproducible():
    y = np.array([0, 1, 0, 2, 0, 0, 3, 0] * 10, dtype=float)
    fw = np.full(13, y.mean())
    a = M.bootstrap_interval(y, fw, 30, np.random.default_rng(1))
    b = M.bootstrap_interval(y, fw, 30, np.random.default_rng(1))
    assert a == b and a[0] <= M.horizon_total(fw, 30) <= a[1]

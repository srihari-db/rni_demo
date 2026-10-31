"""Reproducible demand forecasting pipeline (backtest -> model selection -> final forecast).

Pure pandas/numpy. Spark/MLflow I/O lives in ``scripts/run_forecasting.py``.

Leakage guard: every series is built by ``weekly_series(usage, cutoff)`` which drops observations after the cutoff
before any model sees them; tests assert that appending future rows never changes a forecast.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from . import models as M

HORIZONS = (30, 60, 90)
N_WEEKS = 104
BACKTEST_ORIGINS_DAYS = (91, 182, 273)    # rolling origins before the snapshot
INTERVAL_LEVEL = 0.8
PIPELINE_VERSION = "1.0.0"


def weekly_series(usage: pd.DataFrame, pairs: List[Tuple[str, str]], cutoff: dt.date, n_weeks: int = N_WEEKS
                  ) -> Dict[Tuple[str, str], np.ndarray]:
    """Weekly demand ending at ``cutoff`` (inclusive), oldest first. Rows after the cutoff are discarded."""
    u = usage[["customer_id", "sku", "usage_date", "quantity_consumed"]].copy()
    u["usage_date"] = pd.to_datetime(u.usage_date).dt.date
    u = u[u.usage_date <= cutoff]
    u["wk"] = [(cutoff - d).days // 7 for d in u.usage_date]
    u = u[u.wk < n_weeks]
    agg = u.groupby(["customer_id", "sku", "wk"]).quantity_consumed.sum()
    out = {}
    for p in pairs:
        arr = np.zeros(n_weeks)
        if p in agg.index.droplevel(2):
            s = agg.loc[p]
            arr[(n_weeks - 1 - s.index.values).astype(int)] = s.values
        out[p] = arr
    return out


def actual_totals(usage: pd.DataFrame, origin: dt.date, horizon_days: int) -> pd.Series:
    u = usage.copy()
    u["usage_date"] = pd.to_datetime(u.usage_date).dt.date
    m = (u.usage_date > origin) & (u.usage_date <= origin + dt.timedelta(days=horizon_days))
    return u[m].groupby(["customer_id", "sku"]).quantity_consumed.sum()


def _forecast_one(y, model_name, h=13):
    return M.MODELS[model_name](y, h)


def backtest(usage: pd.DataFrame, pairs, snapshot: dt.date, seed: int = 7) -> pd.DataFrame:
    """Rolling-origin backtest of every model on every series. Returns one row per origin/pair/model/horizon."""
    rows = []
    for off in BACKTEST_ORIGINS_DAYS:
        origin = snapshot - dt.timedelta(days=off)
        series = weekly_series(usage, pairs, origin)
        acts = {h: actual_totals(usage, origin, h) for h in HORIZONS if h <= off}
        for p in pairs:
            y = series[p]
            cls = M.classify_demand(y)
            rng = np.random.default_rng([seed, off] + [ord(c) for c in "".join(p)])
            for name in M.MODELS:
                fw = _forecast_one(y, name)
                for h, act in acts.items():
                    f = M.horizon_total(fw, h)
                    lo, hi = M.bootstrap_interval(y, fw, h, rng, INTERVAL_LEVEL, n_sims=500)
                    a = float(act.get(p, 0.0))
                    rows.append(dict(origin_date=origin, customer_id=p[0], sku=p[1], demand_class=cls["demand_class"],
                                     seasonal=cls["seasonal"], model_name=name, horizon_days=h, forecast=f, actual=a,
                                     lower=lo, upper=hi))
    return pd.DataFrame(rows)


def evaluate(bt: pd.DataFrame) -> pd.DataFrame:
    """Aggregate backtest errors per demand class / model / horizon."""
    def agg(g):
        a, f = g.actual.values, g.forecast.values
        sa = a.sum()
        return pd.Series(dict(
            n_series=len(g),
            mae=float(np.mean(np.abs(f - a))),
            wape=float(np.abs(f - a).sum() / sa) if sa > 0 else np.nan,
            bias=float((f - a).sum() / sa) if sa > 0 else np.nan,
            under_forecast_share=float(np.clip(a - f, 0, None).sum() / sa) if sa > 0 else np.nan,   # stockout-sensitive
            exceed_upper_rate=float(np.mean(a > g.upper.values)),                                  # stockout-sensitive
            interval_coverage=float(np.mean((a >= g.lower.values) & (a <= g.upper.values))),
        ))
    return bt.groupby(["demand_class", "model_name", "horizon_days"]).apply(agg).reset_index()


def select_models(metrics: pd.DataFrame, bt: pd.DataFrame = None) -> Dict[str, dict]:
    """Pick, per demand class, the model with the lowest mean MAE across horizons (simpler model wins ties
    within 2%). MAE is used rather than WAPE because WAPE is undefined/unstable for near-zero-demand classes.

    If the backtest frame is supplied, also fit a split-conformal margin per class/horizon for the selected model:
    the 80th percentile of how far actuals fell outside the bootstrap interval. Widening by this margin restores
    ~80% empirical coverage on held-out origins."""
    sel = {}
    for cls, g in metrics.groupby("demand_class"):
        s = g.groupby("model_name").agg(mae=("mae", "mean"), wape=("wape", "mean"), bias=("bias", "mean"),
                                        under=("under_forecast_share", "mean"), cov=("interval_coverage", "mean"))
        s["rank"] = [M.COMPLEXITY.index(m) for m in s.index]
        best = s.mae.min()
        cands = s[s.mae <= best * 1.02].sort_values("rank")
        name = cands.index[0]
        base = s.loc["MOVING_AVERAGE_12W"]
        sel[cls] = dict(model_name=name, mae=float(s.loc[name, "mae"]), wape=float(s.loc[name, "wape"]),
                        bias=float(s.loc[name, "bias"]), interval_coverage=float(s.loc[name, "cov"]),
                        baseline_mae=float(base.mae),
                        mae_improvement_vs_baseline=float(1 - s.loc[name, "mae"] / base.mae) if base.mae > 0 else 0.0,
                        conformal_margin={})
        if bt is not None:
            b = bt[(bt.demand_class == cls) & (bt.model_name == name)]
            for h, g in b.groupby("horizon_days"):
                score = np.maximum.reduce([g.lower.values - g.actual.values, g.actual.values - g.upper.values,
                                           np.zeros(len(g))])
                sel[cls]["conformal_margin"][int(h)] = float(np.quantile(score, INTERVAL_LEVEL))
    return sel


def forecast(usage: pd.DataFrame, pairs, as_of: dt.date, selection: Dict[str, dict], model_version: str,
             seed: int = 11) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Final forecasts as of ``as_of`` using only observations <= as_of."""
    series = weekly_series(usage, pairs, as_of)
    max_obs = pd.to_datetime(usage.usage_date).dt.date
    max_obs = max(d for d in max_obs if d <= as_of)
    rows, wrows = [], []
    for p in pairs:
        y = series[p]
        cls = M.classify_demand(y)
        mname = selection.get(cls["demand_class"], {}).get("model_name", "MOVING_AVERAGE_12W")
        fw = _forecast_one(y, mname)
        rng = np.random.default_rng([seed] + [ord(c) for c in "".join(p)])
        margins = selection.get(cls["demand_class"], {}).get("conformal_margin", {})
        for h in HORIZONS:
            lo, hi = M.bootstrap_interval(y, fw, h, rng, INTERVAL_LEVEL)
            q = float(margins.get(h, margins.get(str(h), 0.0)))
            lo, hi = max(0.0, lo - q), hi + q
            pt = M.horizon_total(fw, h)
            rows.append(dict(customer_id=p[0], sku=p[1], forecast_date=as_of, forecast_horizon=h,
                             horizon_label=f"{h} days", predicted_demand=round(pt, 3),
                             lower_bound=round(min(lo, pt), 3), upper_bound=round(max(hi, pt), 3),
                             interval_level=INTERVAL_LEVEL, interval_method="BOOTSTRAP_CONFORMAL", model_name=mname, demand_class=cls["demand_class"],
                             seasonal_flag=cls["seasonal"], model_version=model_version,
                             training_cutoff_date=as_of, training_obs_max_date=max_obs,
                             max_weekly_demand_104w=float(y.max()), nonzero_weeks_104w=cls["nonzero_weeks"]))
        for k in range(13):
            lo, hi = M.bootstrap_interval(y, fw[k:k + 1].repeat(1), 7, rng, INTERVAL_LEVEL, n_sims=400)
            wrows.append(dict(customer_id=p[0], sku=p[1], forecast_date=as_of,
                              week_start=as_of + dt.timedelta(days=1 + 7 * k), predicted_weekly_demand=round(float(fw[k]), 3),
                              lower_bound=round(min(lo, fw[k]), 3), upper_bound=round(max(hi, fw[k]), 3),
                              model_name=mname, model_version=model_version))
    return pd.DataFrame(rows), pd.DataFrame(wrows)


def run(usage: pd.DataFrame, pairs, snapshot: dt.date, model_version: str = "local"):
    bt = backtest(usage, pairs, snapshot)
    metrics = evaluate(bt)
    selection = select_models(metrics, bt)
    fc, weekly = forecast(usage, pairs, snapshot, selection, model_version)
    return dict(backtest=bt, metrics=metrics, selection=selection, forecasts=fc, weekly=weekly)

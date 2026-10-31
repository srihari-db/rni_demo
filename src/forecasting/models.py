"""Demand forecasting models for weekly RNI consumption series (numpy only, no external deps).

All functions take a chronological 1-D array of weekly demand ``y`` (oldest first, observations up to the
training cutoff ONLY) and return a weekly point forecast for the next ``h`` weeks.
"""
from __future__ import annotations

from typing import Callable, Dict

import numpy as np

# --------------------------------------------------------------------------------------- classification
SMOOTH, ERRATIC, INTERMITTENT, LUMPY, NO_DEMAND = "SMOOTH", "ERRATIC", "INTERMITTENT", "LUMPY", "NO_RECENT_DEMAND"


def classify_demand(y: np.ndarray) -> dict:
    """Syntetos–Boylan–Croston classification (ADI / CV²) plus a simple year-over-year seasonality test."""
    y = np.asarray(y, dtype=float)
    nz = np.flatnonzero(y > 0)
    if len(nz) == 0:
        return dict(demand_class=NO_DEMAND, adi=float("inf"), cv2=0.0, seasonal=False, nonzero_weeks=0)
    adi = len(y) / len(nz)
    sizes = y[nz]
    cv2 = float((sizes.std() / sizes.mean()) ** 2) if len(sizes) > 1 else 0.0
    if adi < 1.32:
        cls = SMOOTH if cv2 < 0.49 else ERRATIC
    else:
        cls = INTERMITTENT if cv2 < 0.49 else LUMPY
    seasonal = False
    if len(y) >= 104 and adi < 1.32:
        a = np.convolve(y[-104:-52], np.ones(4) / 4, mode="valid")
        b = np.convolve(y[-52:], np.ones(4) / 4, mode="valid")
        if a.std() > 0 and b.std() > 0:
            seasonal = bool(np.corrcoef(a, b)[0, 1] > 0.6)
    return dict(demand_class=cls, adi=float(adi), cv2=cv2, seasonal=seasonal, nonzero_weeks=int(len(nz)))


# --------------------------------------------------------------------------------------- models
def moving_average(y, h, window=12):
    y = np.asarray(y, float)
    return np.full(h, y[-window:].mean() if len(y) else 0.0)


def historical_average(y, h, window=52):
    y = np.asarray(y, float)
    return np.full(h, y[-window:].mean() if len(y) else 0.0)


def ses(y, h, alphas=(0.05, 0.1, 0.2, 0.3, 0.5)):
    """Simple exponential smoothing; alpha chosen by in-sample one-step-ahead SSE (training data only)."""
    y = np.asarray(y, float)
    if len(y) == 0:
        return np.zeros(h)
    best = (np.inf, y[0])
    for a in alphas:
        level, sse = y[0], 0.0
        for v in y[1:]:
            sse += (v - level) ** 2
            level = a * v + (1 - a) * level
        if sse < best[0]:
            best = (sse, level)
    return np.full(h, best[1])


def croston_sba(y, h, alpha=0.1):
    """Croston's method with the Syntetos–Boylan bias approximation for intermittent demand."""
    y = np.asarray(y, float)
    nz = np.flatnonzero(y > 0)
    if len(nz) == 0:
        return np.zeros(h)
    z, p, q = y[nz[0]], float(nz[0] + 1), 1
    for v in y[nz[0] + 1:]:
        if v > 0:
            z = alpha * v + (1 - alpha) * z
            p = alpha * q + (1 - alpha) * p
            q = 1
        else:
            q += 1
    return np.full(h, (1 - alpha / 2) * z / p)


def tsb(y, h, alpha=0.1, beta=0.05):
    """Teunter–Syntetos–Babai: separately smooths demand probability (decays during zero runs)."""
    y = np.asarray(y, float)
    nz = np.flatnonzero(y > 0)
    if len(nz) == 0:
        return np.zeros(h)
    prob, size = len(nz) / len(y), y[nz].mean()
    for v in y:
        prob = beta * (v > 0) + (1 - beta) * prob
        if v > 0:
            size = alpha * v + (1 - alpha) * size
    return np.full(h, prob * size)


def seasonal_naive_adjusted(y, h):
    """Same weeks last year (3-week smoothed) scaled by the recent year-over-year level ratio."""
    y = np.asarray(y, float)
    if len(y) < 52 + 13:
        return moving_average(y, h)
    sm = np.convolve(np.concatenate([y[-53:], y[-52:-50]]), np.ones(3) / 3, mode="valid")[: 52]
    recent, prior = y[-12:].sum(), y[-64:-52].sum()
    ratio = np.clip(recent / prior, 0.5, 2.0) if prior > 0 else 1.0
    idx = np.arange(h) % 52
    return sm[idx] * ratio


MODELS: Dict[str, Callable] = {
    "MOVING_AVERAGE_12W": moving_average,          # baseline
    "HISTORICAL_AVERAGE_52W": historical_average,  # baseline
    "SES": ses,
    "CROSTON_SBA": croston_sba,
    "TSB": tsb,
    "SEASONAL_NAIVE_ADJ": seasonal_naive_adjusted,
}
# complexity order used to break ties (simpler wins)
COMPLEXITY = ["MOVING_AVERAGE_12W", "HISTORICAL_AVERAGE_52W", "SES", "CROSTON_SBA", "TSB", "SEASONAL_NAIVE_ADJ"]


def bootstrap_interval(y, point_weekly: np.ndarray, horizon_days: int, rng: np.random.Generator,
                       level: float = 0.8, n_sims: int = 2000):
    """Empirical bootstrap interval for the horizon total.

    Resamples weekly demand from the last 52 training weeks (all 104 if the last year had no demand), rescaled so
    the resampled mean equals the model's point forecast. Preserves intermittency (zero weeks) and lumpiness.
    """
    y = np.asarray(y, float)
    pool = y[-52:] if (y[-52:] > 0).any() else y[-104:]
    weeks = int(np.ceil(horizon_days / 7))
    frac = horizon_days / (7 * weeks)
    point_mean = float(np.mean(point_weekly[:weeks])) if weeks else 0.0
    if pool.sum() <= 0 or point_mean <= 0:
        return 0.0, 0.0
    scale = point_mean / pool.mean()
    sims = rng.choice(pool, size=(n_sims, weeks), replace=True).sum(axis=1) * scale * frac
    lo, hi = np.quantile(sims, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def horizon_total(point_weekly: np.ndarray, horizon_days: int) -> float:
    weeks = int(np.ceil(horizon_days / 7))
    full = horizon_days // 7
    total = float(np.sum(point_weekly[:full]))
    if weeks > full:
        total += float(point_weekly[full]) * (horizon_days - 7 * full) / 7
    return total

# Demand Forecasting — Model Evaluation Notes

- **MLflow experiment:** `/Users/srihari.a@databricks.com/rni_demo_demand_forecasting`.
- **Registered model:** `rni_demo.ml.rni_demand_forecaster` (latest version is 2, from the most recent pipeline run; every run registers a new version).

## Method

- **Unit of analysis:** weekly consumption per customer/SKU (203 series, 104 weeks). Observations after each cutoff
  are removed *before* any model sees them; `tests/test_forecasting.py` proves that appending future rows changes
  nothing.
- **Classification:** Syntetos–Boylan (ADI / CV²) into SMOOTH, ERRATIC, INTERMITTENT, LUMPY and NO_RECENT_DEMAND,
  plus a year-over-year seasonality test.
- **Candidate models:**
  - 12-week moving average and 52-week average (baselines)
  - simple exponential smoothing (SES)
  - Croston–SBA
  - TSB
  - adjusted seasonal-naive
- **Backtest:** rolling origins at 91, 182 and 273 days before the snapshot; horizons of 30, 60 and 90 days; actuals
  are strictly after the origin.
- **Metrics:**
  - MAE
  - WAPE
  - bias
  - under-forecast share (stockout-sensitive)
  - rate of actuals above the upper bound (stockout-sensitive)
  - interval coverage
- **Selection:** per demand class, lowest mean MAE across horizons; a simpler model wins any tie within 2%. MAE is
  used because WAPE is unstable for near-zero-demand series. Complexity is never assumed to be better.
- **Intervals (80%):** an empirical bootstrap of recent weekly demand, rescaled to the point forecast, then widened
  by a split-conformal margin fitted on the backtest.

## Results (selected model vs 12-week moving-average baseline)

| Class (series) | Selected | Horizon | MAE (baseline) | WAPE (baseline) | Bias | Raw interval coverage |
|---|---|---|---|---|---|---|
| SMOOTH (89) | SEASONAL_NAIVE_ADJ | 30 d | **6.64** (7.09) | 0.185 (0.197) | −0.012 | 0.60 |
| | | 60 d | **10.78** (12.64) | 0.146 (0.172) | −0.012 | 0.62 |
| | | 90 d | **13.44** (20.78) | 0.119 (0.184) | −0.010 | 0.58 |
| INTERMITTENT (102) | TSB | 30 d | 3.67 (**3.52**) | 0.293 (0.281) | 0.002 | 0.79 |
| | | 60 d | **6.04** (6.32) | 0.250 (0.261) | 0.038 | 0.76 |
| | | 90 d | **8.10** (10.00) | 0.231 (0.285) | 0.074 | 0.76 |
| LUMPY (10) | TSB | 30 d | **2.42** (2.82) | 0.873 (1.017) | −0.184 | 0.77 |
| | | 90 d | **3.52** (5.55) | 0.536 (0.844) | 0.032 | 0.74 |
| NO_RECENT_DEMAND (2) | MOVING_AVERAGE_12W | — | baseline | — | — | — |

Notes:

- **Intermittent series:** TSB is slightly *worse* than the baseline at 30 days but better at 60 and 90 days, so it
  wins on the mean across horizons. This is reported as-is.
- **Smooth-series intervals:** raw bootstrap coverage was about 0.60, under the 0.80 target. The conformal margin
  lifted held-out coverage to roughly 0.73–0.91, depending on the class. This is noted in `ml.demand_forecasts`
  (`interval_method = BOOTSTRAP_CONFORMAL`).

## Limitations — rare and intermittent demand

- Emergency products (antivenoms, antidotes, reversal agents) have very few events. Their point forecasts are near
  zero, and the intervals are wide relative to the mean.
- **These forecasts are not a basis for safe stocking.** The decision engine:
  - never lets a forecast reduce stock below the approved mandatory minimum,
  - raises critical-product targets to the largest observed single-week demand,
  - requires human review.
- All accuracy figures describe the synthetic simulator, not FFF operations; real data must be re-evaluated.
- Forecasts are precomputed for the demo (no live training during the presentation).

"""Rolling-baseline anomaly detector for RNI device telemetry (illustrative bonus capability).

Each device is compared with its OWN first-14-day baseline. A 4-hour rolling mean of vibration and temperature is
converted to z-scores; the anomaly score is a logistic transform of the larger z-score. A sustained high score is
an inspection signal — it does not prove that a compressor will fail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASELINE_DAYS = 14
ROLLING = "4h"
THRESHOLD = 0.8
SUSTAIN_READINGS = 4          # >= 1 hour at 15-minute readings


def score(telemetry: pd.DataFrame) -> pd.DataFrame:
    out = []
    for dev, g in telemetry.sort_values("event_timestamp").groupby("device_id"):
        g = g.copy()
        ts = pd.to_datetime(g.event_timestamp)
        base = g[ts < ts.min() + pd.Timedelta(days=BASELINE_DAYS)]
        roll = g.set_index(ts)[["vibration_mm_s", "temperature_c"]].rolling(ROLLING).mean().values
        zv = (roll[:, 0] - base.vibration_mm_s.mean()) / max(base.vibration_mm_s.std(), 1e-6)
        # temperature: rolling mean noise is small, so floor the std to avoid flagging normal cycling
        zt = (roll[:, 1] - base.temperature_c.mean()) / max(base.temperature_c.std(), 0.25)
        z = np.maximum(zv, np.abs(zt))
        s = 1.0 / (1.0 + np.exp(-(z - 4.0)))
        hi = s >= THRESHOLD
        run = pd.Series(hi).groupby((~pd.Series(hi)).cumsum()).cumsum().values
        g["z_vibration"] = np.round(zv, 3)
        g["z_temperature"] = np.round(zt, 3)
        g["anomaly_score"] = np.round(s, 4)
        g["is_anomaly"] = run >= SUSTAIN_READINGS
        out.append(g)
    cols = ["device_id", "customer_id", "event_timestamp", "temperature_c", "vibration_mm_s", "compressor_status",
            "z_vibration", "z_temperature", "anomaly_score", "is_anomaly"]
    return pd.concat(out, ignore_index=True)[cols]

"""Screen 6 (bonus) — RNI Connected Device Intelligence (illustrative IoT extension)."""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import services as svc
import ui

ui.header("RNI Connected Device Intelligence", "Illustrative extension: device telemetry on the same data foundation",
          pill="Illustrative · synthetic telemetry")
health = svc.safe(lambda: svc.load("device_health"), pd.DataFrame())
if health is None or health.empty:
    st.stop()
order = {"HIGH": 0, "MEDIUM": 1, "WATCH": 2, "ROUTINE": 3}
health = health.assign(_o=health.inspection_priority.map(order)).sort_values(["_o", "max_anomaly_score_24h"], ascending=[True, False])

c = st.columns(4)
with c[0]:
    ui.kpi("Connected devices", str(len(health)), "fridges & freezers reporting")
with c[1]:
    ui.kpi("Inspection priority HIGH", str(int((health.inspection_priority == "HIGH").sum())), "anomaly + material inventory", "red")
with c[2]:
    ui.kpi("Watch list", str(int(health.inspection_priority.isin(["MEDIUM", "WATCH"]).sum())), "elevated signal", "amber")
with c[3]:
    top = health.iloc[0]
    ui.kpi("Inventory in top-priority device", ui.usd(top.inventory_value_in_device), top.device_id, "amber")

ui.section("Device health")
st.dataframe(health[["device_id", "customer_name", "device_type", "inspection_priority", "max_anomaly_score_24h",
                     "avg_vibration_24h", "baseline_vibration", "avg_temperature_24h", "inventory_value_in_device",
                     "critical_units_in_device"]], hide_index=True, use_container_width=True,
             column_config={"max_anomaly_score_24h": st.column_config.ProgressColumn("Anomaly score (24 h)", min_value=0, max_value=1),
                            "inventory_value_in_device": st.column_config.NumberColumn("Inventory value", format="$%,.0f")})

dev = st.selectbox("Device", health.device_id.tolist(), format_func=lambda d: f"{d} · {health.set_index('device_id').customer_name[d]}")
hr = svc.safe(lambda: svc.load("device_hourly", device_id=dev), pd.DataFrame())
if hr is not None and len(hr):
    hr["hour"] = pd.to_datetime(hr.hour)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=("Compressor vibration (mm/s, hourly mean)", "Internal temperature (°C, hourly mean)"))
    fig.add_scatter(x=hr.hour, y=hr.avg_vibration_mm_s, line=dict(color=ui.NAVY), name="Vibration", row=1, col=1)
    an = hr[hr.any_anomaly]
    fig.add_scatter(x=an.hour, y=an.avg_vibration_mm_s, mode="markers", marker=dict(color=ui.RED, size=6), name="Anomalous hour", row=1, col=1)
    fig.add_scatter(x=hr.hour, y=hr.avg_temperature_c, line=dict(color=ui.TEAL), name="Temperature", row=2, col=1)
    if hr.avg_temperature_c.mean() > 0:
        fig.add_hrect(y0=2, y1=8, fillcolor="rgba(15,163,163,0.06)", line_width=0, row=2, col=1)
    st.plotly_chart(ui.plotly_layout(fig, 460), use_container_width=True)

row = health.set_index("device_id").loc[dev]
ui.alert(f"<b>Recommended inspection priority: {row.inspection_priority}</b> — max anomaly score {row.max_anomaly_score_24h:.2f} "
         f"in the last 24 h; vibration {row.avg_vibration_24h:.2f} mm/s vs baseline {row.baseline_vibration:.2f}. "
         "A rising vibration signal suggests an inspection; it does not prove an impending compressor failure.",
         "red" if row.inspection_priority == "HIGH" else "teal")
ui.section("Potentially affected inventory in this device")
lots = svc.safe(lambda: svc.load("device_lots", device_id=dev), pd.DataFrame())
if lots is not None and len(lots):
    st.dataframe(lots[["product_name", "lot_id", "on_hand_qty", "expiry_date", "inventory_value", "critical_stock_flag"]],
                 hide_index=True, use_container_width=True,
                 column_config={"inventory_value": st.column_config.NumberColumn("Inventory value", format="$%,.0f")})
with st.expander("Future integration design"):
    st.markdown("""
- **Today (demo):** synthetic 15-minute telemetry in `silver.device_telemetry`, scored by a rolling-baseline detector
  (`src/iot/anomaly.py`) into `ml.device_telemetry_scored`.
- **Next:** stream ClearBlade device messages from Google Cloud Pub/Sub into Unity Catalog with **Zerobus Ingest**
  (direct gRPC writes to Delta) or a retained Pub/Sub → Structured Streaming pipeline; no change to Gold consumers.
- **Then:** join telemetry with lot-level inventory to prioritize inspections by value at risk and critical stock,
  and alert planners through the same case workflow.
""")
ui.footnote("Illustrative only: synthetic telemetry and a simple statistical detector. Not a predictive-maintenance model.")

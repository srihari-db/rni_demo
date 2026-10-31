"""Screen 2 — Intelligent Shipment Advisor (centerpiece): requested vs forecast vs policy-constrained recommendation."""
import dataclasses
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import services as svc
import ui
from src.optimization.batch import input_from_json
from src.optimization.engine import LotPosition, recommend

ui.header("Intelligent Shipment Advisor",
          "Explainable, policy-constrained replenishment recommendation for a customer and product")

pairs = svc.safe(lambda: svc.load("exposure"), pd.DataFrame())
if pairs is None or pairs.empty:
    st.stop()
queue = svc.safe(lambda: svc.load("review_queue"), pd.DataFrame())

default = st.session_state.get("advisor_pair", ("CUST-001", "SKU-1001"))
custs = pairs[["customer_id", "customer_name"]].drop_duplicates().sort_values("customer_id")
c1, c2, c3 = st.columns([1.3, 1.6, 1])
cust_ids = custs.customer_id.tolist()
ci = cust_ids.index(default[0]) if default[0] in cust_ids else 0
cust = c1.selectbox("Customer", cust_ids, index=ci, format_func=lambda x: custs.set_index("customer_id").customer_name[x])
prods = pairs[pairs.customer_id == cust][["sku", "product_name"]].sort_values("sku")
skus = prods.sku.tolist()
si = skus.index(default[1]) if default[1] in skus else 0
sku = c2.selectbox("Product", skus, index=si, format_func=lambda x: prods.set_index("sku").product_name[x])
st.session_state["advisor_pair"] = (cust, sku)

recs = svc.safe(lambda: svc.load("pair_recs", customer_id=cust, sku=sku), pd.DataFrame())
if recs is None or recs.empty:
    st.info("No decision-engine output is available for this customer and product yet.")
    st.stop()
pending = recs[recs.recommendation_type == "SHIPMENT_REQUEST"]
base_rec = (pending if len(pending) else recs[recs.recommendation_type == "CYCLE_REVIEW"]).iloc[0]
inp0 = input_from_json(base_rec.engine_input)
has_request = len(pending) > 0
c3.markdown(ui.badge("Pending request" if has_request else "Cycle review (no open request)",
                     ui.NAVY if has_request else ui.GREY), unsafe_allow_html=True)
if isinstance(base_rec.scenario_id, str):
    c3.markdown(ui.badge(f"Demo scenario {base_rec.scenario_id}", ui.TEAL), unsafe_allow_html=True)

# ------------------------------------------------------------------------------------------- what-if controls
with st.expander("What-if controls — adjust inputs and rerun the decision engine", expanded=True):
    k = f"{cust}-{sku}"
    w1, w2, w3, w4, w5 = st.columns([1, 1, 1, 1, 0.7])
    req = w1.number_input("Requested quantity", min_value=0, value=int(inp0.requested_qty or 0), step=int(inp0.pack_size), key=f"rq{k}")
    par = w2.number_input("PAR target", min_value=0, value=int(inp0.par_level), step=1, key=f"par{k}")
    oh = w3.number_input("Current inventory (on hand)", min_value=0, value=int(inp0.on_hand_qty), step=1, key=f"oh{k}")
    mmin = w4.number_input("Mandatory minimum", min_value=0, value=int(inp0.mandatory_minimum), step=1, key=f"mm{k}")
    if w5.button("Reset", use_container_width=True):
        for p in ("rq", "par", "oh", "mm"):
            st.session_state.pop(f"{p}{k}", None)
        st.rerun()

# adjust lots to the edited on-hand (add/remove from the longest-dated lot) so expiry logic stays consistent
lots = [LotPosition(l.lot_id, l.qty, l.days_to_expiry) for l in inp0.lots]
delta = int(oh) - int(inp0.on_hand_qty)
if delta and lots:
    lots.sort(key=lambda l: l.days_to_expiry)
    if delta > 0:
        lots[-1].qty += delta
    else:
        rem = -delta
        for l in reversed(lots):
            take = min(rem, l.qty)
            l.qty -= take
            rem -= take
elif delta > 0:
    lots = [LotPosition("WHAT-IF", delta, 365)]
inp = dataclasses.replace(inp0, requested_qty=(int(req) if (has_request or req) else None), par_level=int(par),
                          on_hand_qty=int(oh), mandatory_minimum=int(mmin), lots=[l for l in lots if l.qty > 0])
out = recommend(inp, svc.rules())
edited = (inp.requested_qty, inp.par_level, inp.on_hand_qty, inp.mandatory_minimum) != \
         (inp0.requested_qty, inp0.par_level, inp0.on_hand_qty, inp0.mandatory_minimum)

# ------------------------------------------------------------------------------------------- headline
tone = {"EXCESSIVE_REQUEST": "red", "STOCKOUT_RISK": "amber", "EXPIRY_RISK": "amber",
        "CRITICAL_POLICY_HOLD": "amber", "MISSING_DATA": "grey"}.get(out.risk_category, "teal")
ui.alert(f"{ui.badge(out.risk_category.replace('_', ' '), ui.RISK_COLORS.get(out.risk_category, ui.GREY))}"
         f"{ui.badge('Human review required' if out.human_review_required else 'Within policy', ui.NAVY if out.human_review_required else ui.TEAL)}"
         f"{ui.badge('What-if (edited inputs)', ui.AMBER) if edited else ''}"
         f"<br><b>{out.review_reason}</b>", tone)

fc = svc.safe(lambda: svc.load("pair_forecast", customer_id=cust, sku=sku), pd.DataFrame())
f30 = fc[fc.forecast_horizon == 30].iloc[0] if fc is not None and len(fc) else None
k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    ui.kpi("Requested", ui.num(out.requested_qty) if out.requested_qty is not None else "—", "original request", "red" if out.excess_qty else "")
with k2:
    ui.kpi("Current inventory", ui.num(inp.on_hand_qty), f"+{inp.pending_inbound_qty} in transit" if inp.pending_inbound_qty else "on hand")
with k3:
    ui.kpi("PAR · Minimum", f"{inp.par_level} · {inp.mandatory_minimum}", inp.approved_stocking_policy or "policy")
with k4:
    ui.kpi("Used last 120 days", ui.num(inp.consumption_last_120d), "historical consumption")
with k5:
    rng = f"80% range {f30.lower_bound:.1f}–{f30.upper_bound:.1f}" if f30 is not None else ""
    ui.kpi("Forecast demand (30 d)", f"{inp.forecast_qty_30d:.1f}" if inp.forecast_qty_30d is not None else "—", rng, "teal")
with k6:
    ui.kpi("Recommended", ui.num(out.recommended_qty) if out.recommended_qty is not None else "—",
           f"PAR-only baseline: {out.par_only_baseline_qty}", "teal")

# ------------------------------------------------------------------------------------------- comparison + forecast
left, right = st.columns([1, 1.5])
store = svc.get_store_cached()
human = None
try:
    cases = [c for c in store.list_cases() if c.customer_id == cust and c.sku == sku and c.status == "APPROVED"]
    human = cases[0].human_approved_qty if cases else None
except Exception:
    pass
labels = ["Original request", "PAR-only baseline", "Policy-constrained recommendation", "Human-approved decision"]
vals = [out.requested_qty or 0, out.par_only_baseline_qty or 0, out.recommended_qty or 0, human]
colors = [ui.RED, "#9AA5B4", ui.TEAL, ui.NAVY]
fig = go.Figure()
for lab, v, col in zip(labels, vals, colors):
    fig.add_bar(x=[lab], y=[v if v is not None else 0], marker_color=col, name=lab,
                text=[("pending" if v is None else f"{v:,}")], textposition="outside",
                marker_pattern_shape="/" if v is None else "")
fig.update_layout(title="Request vs recommendation (units)", showlegend=False)
left.plotly_chart(ui.plotly_layout(fig, 360, legend=False), use_container_width=True)

hist = svc.safe(lambda: svc.load("pair_usage_weekly", customer_id=cust, sku=sku), pd.DataFrame())
fw = svc.safe(lambda: svc.load("pair_forecast_weekly", customer_id=cust, sku=sku), pd.DataFrame())
fig = go.Figure()
if hist is not None and len(hist):
    h = hist.copy()
    h["week_start"] = pd.to_datetime(h.week_start)
    full = pd.DataFrame({"week_start": pd.date_range(h.week_start.min(), h.week_start.max(), freq="W-MON")})
    h = full.merge(h, how="left").fillna({"consumed_qty": 0}).tail(78)
    fig.add_bar(x=h.week_start, y=h.consumed_qty, name="Historical weekly consumption", marker_color="#7A8CA5")
if fw is not None and len(fw):
    f = fw.copy()
    f["week_start"] = pd.to_datetime(f.week_start)
    fig.add_scatter(x=pd.concat([f.week_start, f.week_start[::-1]]), y=pd.concat([f.upper_bound, f.lower_bound[::-1]]),
                    fill="toself", fillcolor="rgba(15,163,163,0.15)", line=dict(width=0), name="80% forecast range")
    fig.add_scatter(x=f.week_start, y=f.predicted_weekly_demand, name="Forecast (weekly)", line=dict(color=ui.TEAL, width=3))
model = f"{f30.model_name} · {f30.demand_class}" if f30 is not None else ""
fig.update_layout(title=f"Historical usage and forecast — {model}")
right.plotly_chart(ui.plotly_layout(fig, 360), use_container_width=True)

# ------------------------------------------------------------------------------------------- explanation
e1, e2 = st.columns([1.4, 1])
with e1:
    ui.section("Why this recommendation")
    for line in out.explanation:
        st.markdown(f"- {line}")
with e2:
    ui.section("Risk factors")
    st.markdown(ui.chips(out.risk_factors or ["None"]), unsafe_allow_html=True)
    ui.section("Policy constraints")
    for p in out.policy_constraints or ["Standard PAR replenishment policy"]:
        st.markdown(f"- {p}")
    ui.section("Potential inventory exposure")
    ui.kpi("If shipped as requested", ui.usd(out.potential_exposure_value),
           f"{out.excess_qty} units × {ui.usd(inp.unit_cost)} — potential exposure, not realized savings", "red" if out.excess_qty else "teal")

with st.expander("Lot detail and engine inputs"):
    st.dataframe(pd.DataFrame([l.__dict__ for l in inp.lots]), hide_index=True, use_container_width=True)
    st.json({k: v for k, v in dataclasses.asdict(inp).items() if k != "lots"})

b1, b2 = st.columns([1, 3])
if b1.button("Create investigation case →", type="primary", disabled=not out.human_review_required and not has_request):
    st.session_state["case_request"] = dict(customer_id=cust, sku=sku,
                                            order_line_id=base_rec.order_line_id if has_request else None)
    st.switch_page("pages/operations_cases.py")
b2.caption("Creating a case never triggers an SAP shipment or return; a planner records the human decision.")
ui.footnote()

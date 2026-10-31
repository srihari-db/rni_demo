"""Screen 4 — Business Value Simulator (illustrative; separates released inventory, cost avoidance and cash)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import services as svc
import ui
from src.value.simulator import ValueAssumptions, ValueBaseline, simulate

ui.header("Business Value Simulator", "Explore hypothetical impact under your own assumptions — illustrative, not validated FFF financials",
          pill="Illustrative")
k = svc.safe(lambda: svc.load("kpis"), pd.DataFrame())
if k is None or k.empty:
    st.stop()
k = k.iloc[0]
d = ValueAssumptions()
avg_cost = (float(k.return_logistics_cost_12m) / max(int(k.avoidable_returns_count_12m), 1)) if k.avoidable_returns_count_12m else d.cost_per_returned_shipment

with st.sidebar:
    st.markdown("#### Assumptions")
    cost_ret = st.number_input("Cost per returned shipment ($)", 0.0, 5000.0, round(avg_cost, 0), 25.0,
                               help="Default = observed synthetic cold-chain shipping + QA processing per return")
    loss = st.slider("Loss rate on expired inventory", 0.0, 1.0, d.expiry_loss_rate, 0.05)
    avoid = st.slider("Share of excess allocation considered avoidable", 0.0, 1.0, d.avoidable_excess_pct, 0.05)
    exp_red = st.slider("Expiry losses avoidable with earlier signals", 0.0, 1.0, d.expiry_reduction_pct, 0.05)
    carry = st.slider("Annual carrying-cost rate", 0.0, 0.3, d.carrying_cost_rate, 0.01)
    avail = st.slider("Share of unmet demand recovered", 0.0, 1.0, d.availability_improvement_pct, 0.05)
    sol = st.number_input("Annual solution cost ($)", 0.0, 5_000_000.0, d.annual_solution_cost, 25_000.0)

base = ValueBaseline(excess_on_hand_value=float(k.excess_on_hand_value), near_expiry_value=float(k.inventory_approaching_expiration_value),
                     expired_value_12m=float(k.expired_value_12m), avoidable_returns_count_12m=int(k.avoidable_returns_count_12m),
                     avoidable_return_logistics_12m=float(k.estimated_avoidable_logistics_cost_12m),
                     unmet_units_12m=float(k.unmet_units_12m), avg_margin_per_unit=float(k.avg_margin_per_unit or 0))
r = simulate(base, ValueAssumptions(cost_ret, loss, avoid, exp_red, carry, avail, sol))

ui.section("1 · Inventory value released (one-time, working capital — not annual savings)")
a, b, c = st.columns(3)
with a:
    ui.kpi("Excess on hand above PAR", ui.usd(base.excess_on_hand_value), "current, mutually exclusive bucket")
with b:
    ui.kpi("Inventory value released", ui.usd(r.inventory_value_released), f"{avoid:.0%} considered avoidable", "teal")
with c:
    ui.kpi("Approaching expiration (≤90 d)", ui.usd(base.near_expiry_value), "current exposure (not added to benefit)", "amber")

ui.section("2 · Potential annual cost avoidance (illustrative)")
cols = st.columns(4)
items = [("Returns logistics avoided", r.returns_logistics_avoided, f"{base.avoidable_returns_count_12m} avoidable returns × {avoid:.0%} × {ui.usd(cost_ret)}"),
         ("Expiry losses avoided", r.expiry_losses_avoided, f"{ui.usd(base.expired_value_12m)} expired × {loss:.0%} loss × {exp_red:.0%}"),
         ("Carrying cost avoided", r.carrying_cost_avoided, f"released × {carry:.0%}"),
         ("Availability margin protected", r.availability_margin_protected, f"{base.unmet_units_12m:,.0f} unmet units × {avail:.0%}")]
for col, (lab, v, sub) in zip(cols, items):
    with col:
        ui.kpi(lab, ui.usd(v), sub, "teal")

a, b = st.columns([1.4, 1])
fig = go.Figure(go.Waterfall(
    x=[i[0] for i in items] + ["Annual solution cost", "Net annual benefit"],
    measure=["relative"] * 4 + ["relative", "total"],
    y=[i[1] for i in items] + [-r.annual_solution_cost, 0],
    connector={"line": {"color": ui.BORDER}}, increasing={"marker": {"color": ui.TEAL}},
    decreasing={"marker": {"color": ui.RED}}, totals={"marker": {"color": ui.NAVY}}))
fig.update_layout(title="Illustrative annual benefit bridge")
fig.update_yaxes(tickprefix="$", tickformat="~s")
a.plotly_chart(ui.plotly_layout(fig, 360, legend=False), use_container_width=True)
with b:
    ui.kpi("Total potential annual cost avoidance", ui.usd(r.total_annual_cost_avoidance), "sum of the four components", "teal")
    st.write("")
    ui.kpi("Net annual benefit", ui.usd(r.net_annual_benefit), f"after {ui.usd(r.annual_solution_cost)} solution cost",
           "teal" if r.net_annual_benefit >= 0 else "red")
    st.write("")
    ui.kpi("Benefit-to-cost ratio", f"{r.benefit_to_cost_ratio:.2f}×", "cost avoidance ÷ solution cost")

ui.section("3 · Realized cash savings")
ui.alert("<b>Not claimed.</b> Realized cash savings require validation against FFF operational and finance data "
         "(actual return costs, write-offs, contract terms). Inventory released and potential cost avoidance above are kept "
         "separate and are never summed.", "grey")
ui.footnote("ILLUSTRATIVE: computed from synthetic Gold metrics (12 months to the demo as-of date) and the assumptions "
            "on the left. No double counting: expiry avoidance uses historical expired value, which is disjoint from current excess.")

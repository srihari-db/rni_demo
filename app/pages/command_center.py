"""Screen 1 — RNI Inventory Command Center (executive operational overview)."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import services as svc
import ui

ui.header("RNI Inventory Command Center",
          "Inventory deployed at customer sites, potential excess exposure, expiration risk and requests needing review")

exposure = svc.safe(lambda: svc.load("exposure"), pd.DataFrame())
metrics = svc.safe(lambda: svc.load("value_metrics"), pd.DataFrame())
queue = svc.safe(lambda: svc.load("review_queue"), pd.DataFrame())
kpis = svc.safe(lambda: svc.load("kpis"), pd.DataFrame())
if exposure is None or exposure.empty or metrics is None or metrics.empty:
    st.stop()
as_of = pd.to_datetime(kpis.as_of_date.iloc[0]).date() if kpis is not None and len(kpis) else None

# ------------------------------------------------------------------------------------------- filters
f1, f2, f3, f4 = st.columns([1, 1.4, 1.2, 1.6])
regions = f1.multiselect("Region", sorted(exposure.region.unique()), placeholder="All regions")
cust_opts = exposure[exposure.region.isin(regions)] if regions else exposure
customers = f2.multiselect("Customer", sorted(cust_opts.customer_name.unique()), placeholder="All customers")
cats = f3.multiselect("Product category", sorted(exposure.product_category.unique()), placeholder="All categories")
prods = f4.multiselect("Product", sorted(exposure[exposure.product_category.isin(cats)].product_name.unique()
                                         if cats else exposure.product_name.unique()), placeholder="All products")


def apply(df, name_col="customer_name"):
    if df is None or df.empty:
        return df
    m = pd.Series(True, index=df.index)
    if regions and "region" in df:
        m &= df.region.isin(regions)
    if customers and name_col in df:
        m &= df[name_col].isin(customers)
    if cats and "product_category" in df:
        m &= df.product_category.isin(cats)
    if prods and "product_name" in df:
        m &= df.product_name.isin(prods)
    return df[m]


e, mt, q = apply(exposure), apply(metrics), apply(queue)

# ------------------------------------------------------------------------------------------- KPI cards
c = st.columns(6)
with c[0]:
    ui.kpi("Total inventory deployed", ui.usd(e.inventory_value.sum()), f"{ui.num(e.on_hand_qty.sum())} units on hand")
with c[1]:
    ui.kpi("Potential excess exposure", ui.usd(mt.potential_excess_exposure_value.sum()),
           f"{ui.usd(mt.potential_excess_value.sum())} above PAR + {ui.usd(mt.pending_request_exposure_value.sum())} in requests",
           "red")
with c[2]:
    ui.kpi("Approaching expiration", ui.usd(e.near_expiry_value.sum()), "lots expiring ≤ 90 days", "amber")
with c[3]:
    n_rev = int(q.human_review_required.sum()) if len(q) else 0
    ui.kpi("Requests requiring review", f"{n_rev}", f"of {len(q)} pending shipment requests", "amber")
with c[4]:
    ui.kpi("Returns value (12 mo)", ui.usd(mt.returned_value.sum()), f"{ui.num(mt.returns_count_12m.sum())} returns", "")
with c[5]:
    ui.kpi("Est. avoidable logistics (12 mo)", ui.usd(mt.avoidable_logistics_cost_12m.sum()),
           "cold-chain + QA cost of over-allocation returns", "teal")

# ------------------------------------------------------------------------------------------- scenario alert
scn = queue[queue.scenario_id == "SCN-01"] if queue is not None and len(queue) else pd.DataFrame()
if len(scn):
    r = scn.iloc[0]
    ui.alert(f"<b>⚠ Potentially excessive request — {r.customer_name} · {r.product_name}</b><br>"
             f"Requested <b>{int(r.requested_qty)}</b> doses · consumed <b>{int(r.consumed_last_120d)}</b> in the last 120 days · "
             f"on hand {int(r.on_hand_qty)} vs PAR {int(r.par_level)} (minimum {int(r.mandatory_minimum)}) · "
             f"engine recommends <b>{int(r.recommended_qty)}</b> · potential exposure <b>{ui.usd(r.potential_exposure_value)}</b>",
             "red")
    if st.button("Open in Intelligent Shipment Advisor →", type="primary"):
        st.session_state["advisor_pair"] = (r.customer_id, r.sku)
        st.switch_page("pages/shipment_advisor.py")

# ------------------------------------------------------------------------------------------- charts row 1
BUCKET_COLORS = {"Excess above PAR": ui.RED, "Approaching expiry": ui.AMBER, "Healthy": ui.TEAL}


def stacked(df, by, title):
    g = df.groupby(by)[["excess_value", "near_expiry_value", "healthy_value"]].sum().reset_index()
    g = g.rename(columns={"excess_value": "Excess above PAR", "near_expiry_value": "Approaching expiry", "healthy_value": "Healthy"})
    g["total"] = g[["Excess above PAR", "Approaching expiry", "Healthy"]].sum(axis=1)
    g = g.sort_values("total")
    m = g.melt(id_vars=[by, "total"], var_name="Bucket", value_name="Value")
    fig = px.bar(m, y=by, x="Value", color="Bucket", orientation="h", title=title, color_discrete_map=BUCKET_COLORS)
    fig.update_xaxes(tickprefix="$", tickformat="~s")
    return ui.plotly_layout(fig, 320)


a, b = st.columns(2)
a.plotly_chart(stacked(e, "region", "Inventory exposure by region (mutually exclusive buckets)"), use_container_width=True)
b.plotly_chart(stacked(e, "product_category", "Inventory exposure by product category"), use_container_width=True)

# ------------------------------------------------------------------------------------------- charts row 2
mon = apply(svc.safe(lambda: svc.load("consumption_monthly"), pd.DataFrame()))
ret = apply(svc.safe(lambda: svc.load("returns"), pd.DataFrame()))
a, b = st.columns(2)
if mon is not None and len(mon):
    g = mon.groupby("month")[["consumed_value", "shipped_value", "returned_value"]].sum().reset_index()
    fig = go.Figure()
    fig.add_scatter(x=g.month, y=g.shipped_value, name="Shipped to sites (movement)", line=dict(color=ui.NAVY, width=3))
    fig.add_scatter(x=g.month, y=g.consumed_value, name="Consumed at sites (utilization)", line=dict(color=ui.TEAL, width=3))
    fig.add_bar(x=g.month, y=g.returned_value, name="Returned", marker_color=ui.AMBER, opacity=0.6)
    fig.update_layout(title="Historical consumption vs shipments (inventory value)")
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    a.plotly_chart(ui.plotly_layout(fig, 330), use_container_width=True)
if ret is not None and len(ret):
    r12 = ret[ret.in_last_12_months].copy()
    g = r12.groupby(["return_month", "potentially_avoidable"]).agg(value=("returned_value", "sum"),
                                                                    cost=("return_logistics_cost", "sum")).reset_index()
    g["Return type"] = g.potentially_avoidable.map({True: "Over-allocation (potentially avoidable)", False: "Short-dated / other"})
    fig = px.bar(g, x="return_month", y="value", color="Return type", title="Return trends — last 12 months (returned value)",
                 color_discrete_map={"Over-allocation (potentially avoidable)": ui.RED, "Short-dated / other": "#7A8CA5"},
                 hover_data={"cost": ":$,.0f"})
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    b.plotly_chart(ui.plotly_layout(fig, 330), use_container_width=True)

# ------------------------------------------------------------------------------------------- charts row 3
a, b = st.columns(2)
top = mt.groupby("customer_name")[["potential_excess_value", "pending_request_exposure_value"]].sum()
top["total"] = top.sum(axis=1)
top = top.sort_values("total", ascending=False).head(10).iloc[::-1].reset_index()
fig = go.Figure()
fig.add_bar(y=top.customer_name, x=top.potential_excess_value, name="Excess on hand above PAR", orientation="h", marker_color=ui.RED)
fig.add_bar(y=top.customer_name, x=top.pending_request_exposure_value, name="Pending request exposure", orientation="h",
            marker_color="#F08A8A")
fig.update_layout(barmode="stack", title="Top 10 locations by potential excess inventory exposure")
fig.update_xaxes(tickprefix="$", tickformat="~s")
a.plotly_chart(ui.plotly_layout(fig, 360), use_container_width=True)
exp = apply(svc.safe(lambda: svc.load("expiry"), pd.DataFrame()))
if exp is not None and len(exp):
    g = exp.groupby(["expiry_horizon_order", "expiry_horizon"]).inventory_value.sum().reset_index().sort_values("expiry_horizon_order")
    colors = [ui.RED, ui.RED, ui.AMBER, ui.AMBER, "#7A8CA5", ui.TEAL][: len(g)]
    fig = px.bar(g, x="expiry_horizon", y="inventory_value", title="Expiration risk by time horizon (inventory value)")
    fig.update_traces(marker_color=[{1: ui.RED, 2: ui.RED, 3: ui.AMBER, 4: ui.AMBER, 5: "#7A8CA5", 6: ui.TEAL}[int(o)]
                                    for o in g.expiry_horizon_order])
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    b.plotly_chart(ui.plotly_layout(fig, 360, legend=False), use_container_width=True)

# ------------------------------------------------------------------------------------------- review table
ui.section("High-priority shipment requests for review")
if q is not None and len(q):
    tbl = q[["review_priority", "customer_name", "product_name", "requested_qty", "recommended_qty", "on_hand_qty",
             "par_level", "consumed_last_120d", "risk_category", "potential_exposure_value", "human_review_required",
             "scenario_id", "customer_id", "sku"]].copy()
    search = st.text_input("Search requests", placeholder="Filter by customer, product or risk…", label_visibility="collapsed")
    if search:
        s = search.lower()
        tbl = tbl[tbl.apply(lambda r: s in f"{r.customer_name} {r.product_name} {r.risk_category}".lower(), axis=1)]
    event = st.dataframe(
        tbl.drop(columns=["customer_id", "sku"]), hide_index=True, use_container_width=True, on_select="rerun",
        selection_mode="single-row",
        column_config={
            "review_priority": st.column_config.NumberColumn("Priority", width="small"),
            "customer_name": "Customer", "product_name": "Product",
            "requested_qty": st.column_config.NumberColumn("Requested"),
            "recommended_qty": st.column_config.NumberColumn("Engine rec."),
            "on_hand_qty": "On hand", "par_level": "PAR", "consumed_last_120d": "Used (120 d)",
            "risk_category": "Risk", "potential_exposure_value": st.column_config.NumberColumn("Potential exposure", format="$%,.0f"),
            "human_review_required": st.column_config.CheckboxColumn("Review"), "scenario_id": "Demo scenario"})
    rows = event.selection.rows if event and hasattr(event, "selection") else []
    if rows:
        r = tbl.iloc[rows[0]]
        st.session_state["advisor_pair"] = (r.customer_id, r.sku)
        st.switch_page("pages/shipment_advisor.py")
    st.caption("Select a row to drill into the Intelligent Shipment Advisor.")

ui.footnote(f"As of {as_of}. Potential exposure = excess on hand above PAR + (requested − recommended) × unit value for "
            "pending flagged requests. It is potential exposure, not realized savings. All data synthetic.")

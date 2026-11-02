"""Screen 5 — AI Operations Case: create and review investigation cases for flagged shipment requests."""
import json

import pandas as pd
import streamlit as st

import services as svc
import ui
from src.agents.cases import APPROVED, NEEDS_INFO, PENDING, REJECTED, REVIEWER_ROLES, TRANSITIONS, transition

ui.header("AI Operations Cases", "AI-assisted investigation of flagged requests — every decision stays with a human planner")
store = svc.get_store_cached()
st.markdown(ui.badge(f"Case store: {store.label}", ui.TEAL if "Lakebase" in store.label else ui.AMBER), unsafe_allow_html=True)
user, role = svc.current_user(), svc.current_role()

queue = svc.safe(lambda: svc.load("review_queue"), pd.DataFrame())
STATUS_COLOR = {PENDING: ui.AMBER, APPROVED: ui.TEAL, REJECTED: ui.RED, NEEDS_INFO: "#7A8CA5"}

# ------------------------------------------------------------------------------------------- create case
ui.section("Open an investigation")
req = st.session_state.pop("case_request", None)
flagged = queue[queue.human_review_required] if queue is not None and len(queue) else pd.DataFrame()
if len(flagged):
    opts = flagged.order_line_id.tolist()
    labels = {r.order_line_id: f"#{r.review_priority} · {r.customer_name} · {r.product_name} · req {r.requested_qty} vs rec {r.recommended_qty} · {r.risk_category}"
              for r in flagged.itertuples()}
    idx = 0
    if req and req.get("order_line_id") in opts:
        idx = opts.index(req["order_line_id"])
    c1, c2 = st.columns([3, 1])
    sel = c1.selectbox("Flagged shipment request", opts, index=idx, format_func=lambda x: labels[x])
    row = flagged[flagged.order_line_id == sel].iloc[0]
    auto = bool(req) and req.get("order_line_id") == sel and not st.session_state.get(f"created_{sel}")
    if c2.button("Create case with AI summary", type="primary", use_container_width=True) or auto:
        with st.spinner("Gathering facts, rerunning the decision engine and drafting a summary…"):
            try:
                case = svc.workflow().create_case(row.customer_id, row.sku, sel, user, role)
                st.session_state["open_case"] = case.case_id
                st.session_state[f"created_{sel}"] = True
                st.success(f"Case {case.case_id} created — pending review.")
            except PermissionError:
                st.error("You are not authorized to open investigation cases.")
            except Exception:
                svc.log.exception("case creation failed")
                st.info("The case could not be created right now. Please retry.")
else:
    st.caption("No flagged requests are pending.")

# ------------------------------------------------------------------------------------------- case list
cases = svc.safe(lambda: store.list_cases(), [])
ui.section(f"Investigation cases ({len(cases)})")
if cases:
    df = pd.DataFrame([dict(case_id=c.case_id, status=c.status, customer=c.customer_name, product=c.product_name,
                            requested=c.requested_qty, recommended=c.recommended_qty, human_approved=c.human_approved_qty,
                            risk=c.risk_category, reviewer=c.reviewer, created_at=c.created_at, updated_at=c.updated_at)
                       for c in cases])
    ev = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row")
    if ev and ev.selection.rows:
        st.session_state["open_case"] = df.iloc[ev.selection.rows[0]].case_id

cid = st.session_state.get("open_case")
case = store.get_case(cid) if cid else None
if case:
    st.markdown("---")
    h1, h2 = st.columns([3, 1])
    h1.markdown(f"### {case.case_id} · {case.customer_name} · {case.product_name}")
    h2.markdown(ui.badge(case.status.replace("_", " "), STATUS_COLOR.get(case.status, ui.GREY)) +
                ui.badge(case.risk_category.replace("_", " "), ui.RISK_COLORS.get(case.risk_category, ui.GREY)),
                unsafe_allow_html=True)
    k = st.columns(4)
    with k[0]:
        ui.kpi("Requested", ui.num(case.requested_qty), "original request", "red")
    with k[1]:
        ui.kpi("Engine recommended", ui.num(case.recommended_qty), "deterministic decision engine", "teal")
    with k[2]:
        ui.kpi("Human-approved", ui.num(case.human_approved_qty) if case.human_approved_qty is not None else "—", "planner decision")
    with k[3]:
        ui.kpi("Potential exposure", ui.usd(case.evidence.get("potential_exposure_value")), "if shipped as requested", "amber")

    a, b = st.columns([1.3, 1])
    with a:
        st.markdown(f"**AI-generated summary** {ui.badge(case.summary_source, ui.NAVY if case.summary_source.startswith('LLM') else ui.GREY)}",
                    unsafe_allow_html=True)
        st.markdown(case.ai_summary)
        st.markdown("**Risk explanation**")
        st.markdown(case.risk_explanation)
        st.markdown("**Proposed next action (for human review)**")
        st.markdown(case.proposed_next_action)
        st.markdown("**Missing information / policy constraints**")
        for m in case.missing_information + case.evidence.get("policy_constraints", []):
            st.markdown(f"- {m}")
    with b:
        st.markdown("**Evidence**")
        ev_ = case.evidence
        st.dataframe(pd.DataFrame([
            ("On hand", ev_.get("on_hand_qty")), ("PAR", ev_.get("par_level")), ("Mandatory minimum", ev_.get("mandatory_minimum")),
            ("Consumed last 120 d", ev_.get("consumed_last_120d")), ("Forecast 30 d", round(ev_.get("forecast_30d_qty", 0), 2)),
            ("PAR-only baseline", ev_.get("par_only_baseline_qty")), ("Returns (12 mo)", ev_.get("returns", {}).get("returns_12m")),
            ("Return logistics (12 mo)", ev_.get("returns", {}).get("return_logistics_cost_12m"))],
            columns=["Fact", "Value"]).astype(str), hide_index=True, use_container_width=True)
        with st.expander("Engine explanation"):
            for line in ev_.get("engine_explanation", []):
                st.markdown(f"- {line}")
        st.caption(f"Created by {case.created_by} · {case.created_at} · updated {case.updated_at}")
        st.caption(f"SAP action: {case.sap_action}")

    allowed = sorted(TRANSITIONS.get(case.status, set()))
    if allowed:
        with st.form(f"review_{case.case_id}"):
            st.markdown("**Planner review**")
            f1, f2 = st.columns([1, 1])
            new = f1.selectbox("Decision", allowed, format_func=lambda s: s.replace("_", " ").title())
            qty = f2.number_input("Human-approved quantity (if approving)", min_value=0,
                                  value=int(case.recommended_qty or 0), step=1)
            comments = st.text_area("Reviewer comments", placeholder="Required to reject or request more information")
            if st.form_submit_button("Submit review", type="primary"):
                before = case.status
                try:
                    transition(case, new, user, role, comments, qty if new == APPROVED else None)
                    store.record_review(case, before)
                    store.log_activity(case.case_id, f"STATUS_{new}", user, {"from": before, "qty": qty if new == APPROVED else None})
                    st.success(f"Case moved to {new.replace('_', ' ').title()}. No SAP transaction was created.")
                    st.rerun()
                except Exception as e:
                    st.warning(str(e))
    else:
        st.info(f"This case is {case.status.replace('_', ' ').lower()} (final).")

# ------------------------------------------------------------------------------------------- admin
if role in REVIEWER_ROLES:
    st.markdown("---")
    with st.expander("Administration"):
        with st.form("reset_cases"):
            st.markdown("**Reset Cases** — permanently deletes all investigation cases with their reviews, overrides "
                        "and activity history.")
            confirm = st.text_input("Type RESET to confirm")
            if st.form_submit_button("Reset Cases"):
                if confirm.strip() != "RESET":
                    st.warning("Type RESET to confirm.")
                else:
                    try:
                        n = store.reset_cases(user)
                        st.session_state.pop("open_case", None)
                        st.success(f"{n} case{'s' if n != 1 else ''} deleted.")
                        st.rerun()
                    except Exception:
                        svc.log.exception("case reset failed")
                        st.info("Cases could not be reset right now. Please retry.")
ui.footnote("Cases are decision-support records. Approving a case records a human decision only; it does not create "
            "or modify any SAP shipment or return.")

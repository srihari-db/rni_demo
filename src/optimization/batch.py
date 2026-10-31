"""Builds decision-engine inputs from curated tables and runs the engine in batch.

Used by ``scripts/run_recommendations.py`` (Databricks job) and by tests. The App uses
``build_input_for_pair`` with live-edited values to rerun the same engine interactively.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Dict, List, Optional

import pandas as pd

from .engine import EngineRules, LotPosition, RecommendationInput, recommend


def _d(x) -> dt.date:
    return pd.to_datetime(x).date()


def build_context(t: Dict[str, pd.DataFrame], forecasts: pd.DataFrame, snapshot: dt.date) -> dict:
    """Pre-index everything the engine needs, as of ``snapshot``. Only data dated <= snapshot is used."""
    pos = t["inventory_positions"]
    cur = pos[pd.to_datetime(pos.snapshot_date).dt.date == snapshot]
    lots = {}
    for r in cur.itertuples():
        lots.setdefault((r.customer_id, r.sku), []).append(
            LotPosition(r.lot_id, int(r.on_hand_qty), (_d(r.expiry_date) - snapshot).days))
    so = t["shipment_orders"]
    inbound = so[so.order_status == "IN_TRANSIT"].groupby(["customer_id", "sku"]).shipped_qty.sum().to_dict()
    ro = t["return_orders"]
    ro12 = ro[pd.to_datetime(ro.return_date).dt.date > snapshot - dt.timedelta(days=365)]
    rcount = ro12.groupby(["customer_id", "sku"]).size().to_dict()
    rcost = ro12.groupby(["customer_id", "sku"]).return_shipping_cost.sum().to_dict()
    u = t["usage_history"]
    u = u[pd.to_datetime(u.usage_date).dt.date <= snapshot]
    u120 = u[pd.to_datetime(u.usage_date).dt.date > snapshot - dt.timedelta(days=120)]
    cons120 = u120.groupby(["customer_id", "sku"]).quantity_consumed.sum().to_dict()
    rules = t["dosing_rules"]
    eff = rules[pd.to_datetime(rules.effective_date).dt.date <= snapshot]
    eff = eff[eff.superseded_date.isna() | (pd.to_datetime(eff.superseded_date).dt.date > snapshot)]
    f30 = forecasts[forecasts.forecast_horizon == 30].set_index(["customer_id", "sku"])
    return dict(
        snapshot=snapshot, lots=lots, inbound=inbound, rcount=rcount, rcost=rcost, cons120=cons120,
        par=t["par_levels"].set_index(["customer_id", "sku"]),
        prod=t["product_master"].set_index("sku"),
        rules=eff.set_index("sku"),
        f30=f30,
    )


def build_input_for_pair(ctx: dict, customer_id: str, sku: str, requested_qty: Optional[int]) -> RecommendationInput:
    k = (customer_id, sku)
    par = ctx["par"].loc[k] if k in ctx["par"].index else None
    prod = ctx["prod"].loc[sku]
    rule = ctx["rules"].loc[sku] if sku in ctx["rules"].index else None
    fc = ctx["f30"].loc[k] if k in ctx["f30"].index else None
    lots = ctx["lots"].get(k, [])
    return RecommendationInput(
        customer_id=customer_id, sku=sku, requested_qty=None if requested_qty is None else int(requested_qty),
        on_hand_qty=int(sum(l.qty for l in lots)),
        par_level=None if par is None else int(par.par_level),
        mandatory_minimum=None if par is None else int(par.mandatory_minimum),
        lead_time_days=None if par is None else int(par.replenishment_lead_time_days),
        forecast_qty_30d=None if fc is None else float(fc.predicted_demand),
        forecast_upper_30d=None if fc is None else float(fc.upper_bound),
        forecast_lower_30d=None if fc is None else float(fc.lower_bound),
        pending_inbound_qty=int(ctx["inbound"].get(k, 0)),
        pack_size=int(prod.pack_size), unit_cost=float(prod.unit_cost),
        critical_stock_flag=bool(prod.critical_stock_flag),
        policy_review_required=bool(rule.review_required) if rule is not None else False,
        approved_stocking_policy="" if rule is None else str(rule.approved_stocking_policy),
        max_weekly_demand_hist=0.0 if fc is None else float(fc.max_weekly_demand_104w),
        lots=lots,
        consumption_last_120d=float(ctx["cons120"].get(k, 0)),
        returns_count_12m=int(ctx["rcount"].get(k, 0)),
        returns_cost_12m=float(ctx["rcost"].get(k, 0.0)),
    )


def run_batch(t: Dict[str, pd.DataFrame], forecasts: pd.DataFrame, snapshot: dt.date, rules: EngineRules,
              model_version: str, created_at: Optional[dt.datetime] = None) -> pd.DataFrame:
    """Engine output for (a) every pending shipment request and (b) a cycle review of every assigned pair."""
    ctx = build_context(t, forecasts, snapshot)
    created_at = created_at or dt.datetime.combine(snapshot, dt.time(23, 59))
    so = t["shipment_orders"]
    pending = so[so.order_status == "PENDING_REVIEW"]
    jobs = [("SHIPMENT_REQUEST", r.order_line_id, r.customer_id, r.sku, int(r.requested_qty), r.scenario_id)
            for r in pending.itertuples()]
    jobs += [("CYCLE_REVIEW", None, r.customer_id, r.sku, None, r.scenario_id)
             for r in t["customer_product_assignments"].itertuples()]
    rows: List[dict] = []
    for i, (kind, line, c, s, req, scn) in enumerate(jobs, start=1):
        inp = build_input_for_pair(ctx, c, s, req)
        out = recommend(inp, rules)
        d = out.to_dict()
        rows.append(dict(
            recommendation_id=f"REC-{snapshot:%y%m%d}-{i:05d}", recommendation_type=kind, order_line_id=line,
            scenario_id=scn if isinstance(scn, str) else None,
            customer_id=c, sku=s, requested_qty=req, on_hand_qty=inp.on_hand_qty, pending_inbound_qty=inp.pending_inbound_qty,
            par_level=inp.par_level, mandatory_minimum=inp.mandatory_minimum, lead_time_days=inp.lead_time_days,
            forecast_qty=inp.forecast_qty_30d, forecast_upper=inp.forecast_upper_30d, forecast_lower=inp.forecast_lower_30d,
            recommended_qty=d["recommended_qty"], par_only_baseline_qty=d["par_only_baseline_qty"],
            target_inventory=d["target_inventory"], effective_available_qty=d["effective_available_qty"],
            projected_expiring_unused_qty=d["projected_expiring_unused_qty"], near_expiry_qty=d["near_expiry_qty"],
            excess_qty=d["excess_qty"], potential_exposure_value=d["potential_exposure_value"],
            request_cover_days=d["request_cover_days"], risk_category=d["risk_category"],
            risk_factors=json.dumps(d["risk_factors"]), policy_constraints=json.dumps(d["policy_constraints"]),
            human_review_required=d["human_review_required"], review_reason=d["review_reason"],
            explanation=json.dumps(d["explanation"]), engine_input=json.dumps(_input_json(inp)),
            model_version=model_version, engine_version=d["engine_version"], rule_version=d["rule_version"],
            snapshot_date=snapshot, created_at=created_at))
    return pd.DataFrame(rows)


def _input_json(inp: RecommendationInput) -> dict:
    d = dict(inp.__dict__)
    d["lots"] = [l.__dict__ for l in inp.lots]
    return d


def input_from_json(s: str) -> RecommendationInput:
    d = json.loads(s)
    d["lots"] = [LotPosition(**l) for l in d.get("lots", [])]
    return RecommendationInput(**d)

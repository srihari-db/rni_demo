"""RNI replenishment decision engine — deterministic, explainable, independently testable.

Pure Python (stdlib only) so the identical code runs in the Databricks job, inside the Databricks App (live
what-if controls) and in unit tests. An LLM is never used to compute quantities.

Algorithm (all quantities in units of the SKU's unit of measure)
--------------------------------------------------------------
1.  Validate inputs; missing PAR / on-hand / minimum / forecast  ->  no quantity, MISSING_DATA, human review.
2.  coverage_days        = replenishment lead time + review period (time until the next replenishment can land)
3.  demand_target        = upper bound of the forecast interval over coverage_days (service-level sizing)
       critical products : max(demand_target, largest historical single-week demand)  — a forecast based on
                           recent history must not shrink emergency coverage below a credible event size
4.  target_inventory     = clamp(demand_target, floor = mandatory minimum, ceiling = PAR)
       -> the forecast can never push the target below the approved mandatory minimum, nor above the
          contracted PAR without review (DEMAND_EXCEEDS_PAR is flagged instead)
5.  usable_on_hand       = on_hand - stock expiring inside the coverage window
    effective_available  = usable_on_hand + pending inbound shipments
    expiry risk          = near-expiry lots (<= 90 d) projected, FEFO at the forecast rate, to expire unused
6.  recommended_qty      = round_up_to_pack( max(0, target_inventory - effective_available) )
7.  Compare with the request -> excess units / exposure value / cover days; classify the primary risk
8.  Human review is mandatory for: excessive or under-sized requests, critical products, policy-flagged SKUs,
    missing data, high exposure, or a high-returns history.

The simplified PAR-only baseline (PAR - on_hand) is reported for comparison only.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Sequence

ENGINE_VERSION = "1.0.0"

RISK_PRIORITY = ["MISSING_DATA", "EXCESSIVE_REQUEST", "STOCKOUT_RISK", "EXPIRY_RISK", "CRITICAL_POLICY_HOLD",
                 "WITHIN_POLICY"]


@dataclass
class EngineRules:
    review_period_days: int = 7
    forecast_horizon_days: int = 30
    use_forecast_bound: str = "upper"
    ratio_threshold: float = 2.0
    abs_threshold_units: int = 10
    max_cover_days: int = 180
    near_expiry_days: int = 90
    expiry_risk_value_threshold: float = 10000.0
    expiry_risk_share_threshold: float = 0.25
    min_cover_ratio: float = 1.0
    high_exposure_value_threshold: float = 25000.0
    high_returns_count_12m: int = 4
    high_returns_cost_12m: float = 1500.0
    critical_products_always_review: bool = True
    rule_version: str = "rules-1.0.0"

    @classmethod
    def from_config(cls, cfg: dict) -> "EngineRules":
        c = cfg or {}
        return cls(
            review_period_days=int(c.get("coverage", {}).get("review_period_days", 7)),
            forecast_horizon_days=int(c.get("coverage", {}).get("forecast_horizon_days", 30)),
            use_forecast_bound=str(c.get("coverage", {}).get("use_forecast_bound", "upper")),
            ratio_threshold=float(c.get("excess_detection", {}).get("ratio_threshold", 2.0)),
            abs_threshold_units=int(c.get("excess_detection", {}).get("abs_threshold_units", 10)),
            max_cover_days=int(c.get("excess_detection", {}).get("max_cover_days", 180)),
            near_expiry_days=int(c.get("expiry", {}).get("near_expiry_days", 90)),
            expiry_risk_value_threshold=float(c.get("expiry", {}).get("expiry_risk_value_threshold", 10000)),
            expiry_risk_share_threshold=float(c.get("expiry", {}).get("expiry_risk_share_threshold", 0.25)),
            min_cover_ratio=float(c.get("stockout", {}).get("min_cover_ratio", 1.0)),
            high_exposure_value_threshold=float(c.get("review", {}).get("high_exposure_value_threshold", 25000)),
            high_returns_count_12m=int(c.get("review", {}).get("high_returns_count_12m", 4)),
            high_returns_cost_12m=float(c.get("review", {}).get("high_returns_cost_12m", 1500)),
            critical_products_always_review=bool(c.get("review", {}).get("critical_products_always_review", True)),
            rule_version=f"rules-{c.get('engine_version', ENGINE_VERSION)}",
        )


@dataclass
class LotPosition:
    lot_id: str
    qty: int
    days_to_expiry: int


@dataclass
class RecommendationInput:
    customer_id: str
    sku: str
    requested_qty: Optional[int]
    on_hand_qty: Optional[int]
    par_level: Optional[int]
    mandatory_minimum: Optional[int]
    lead_time_days: Optional[int]
    forecast_qty_30d: Optional[float]          # point forecast for the forecast horizon
    forecast_upper_30d: Optional[float]        # upper bound of the forecast interval
    forecast_lower_30d: Optional[float] = None
    pending_inbound_qty: int = 0
    pack_size: int = 1
    unit_cost: float = 0.0
    critical_stock_flag: bool = False
    policy_review_required: bool = False
    approved_stocking_policy: str = ""
    max_weekly_demand_hist: float = 0.0        # largest single-week demand in the history window
    lots: Sequence[LotPosition] = field(default_factory=list)
    consumption_last_120d: Optional[float] = None
    returns_count_12m: int = 0
    returns_cost_12m: float = 0.0


@dataclass
class Recommendation:
    customer_id: str
    sku: str
    requested_qty: Optional[int]
    recommended_qty: Optional[int]
    par_only_baseline_qty: Optional[int]
    target_inventory: Optional[int]
    effective_available_qty: Optional[float]
    usable_on_hand_qty: Optional[float]
    projected_expiring_unused_qty: float
    near_expiry_qty: int
    coverage_days: Optional[int]
    demand_over_coverage: Optional[float]
    demand_target: Optional[float]
    excess_qty: int
    potential_exposure_value: float
    request_cover_days: Optional[float]
    risk_category: str
    risk_factors: List[str]
    policy_constraints: List[str]
    missing_information: List[str]
    human_review_required: bool
    review_reason: str
    explanation: List[str]
    engine_version: str = ENGINE_VERSION
    rule_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def round_up_to_pack(qty: float, pack: int) -> int:
    if qty <= 0:
        return 0
    pack = max(int(pack or 1), 1)
    return int(math.ceil(round(qty, 6) / pack) * pack)


def project_expiring_unused(lots: Sequence[LotPosition], daily_rate: float) -> float:
    """FEFO projection: total units forecast to still be on hand when their lot expires."""
    unused, consumed_before = 0.0, 0.0
    for lot in sorted(lots, key=lambda l: l.days_to_expiry):
        capacity = max(0.0, daily_rate * max(lot.days_to_expiry, 0) - consumed_before)
        used = min(float(lot.qty), capacity)
        consumed_before += used
        unused += float(lot.qty) - used
    return unused


def recommend(inp: RecommendationInput, rules: Optional[EngineRules] = None) -> Recommendation:
    r = rules or EngineRules()
    missing = [n for n, v in [("on_hand_qty", inp.on_hand_qty), ("par_level", inp.par_level),
                              ("mandatory_minimum", inp.mandatory_minimum), ("lead_time_days", inp.lead_time_days),
                              ("forecast", inp.forecast_qty_30d)] if v is None]
    explanation: List[str] = []
    policy: List[str] = []
    factors: List[str] = []
    par_base = max(0, int(inp.par_level) - int(inp.on_hand_qty)) if inp.par_level is not None and inp.on_hand_qty is not None else None

    if missing:
        return Recommendation(
            inp.customer_id, inp.sku, inp.requested_qty, None, par_base, None, None, None, 0.0, 0, None, None, None, 0,
            0.0, None, "MISSING_DATA", ["MISSING_DATA"], [], missing, True,
            "Required inputs are missing; a planner must review before any quantity is proposed.",
            [f"Cannot calculate a recommendation: missing {', '.join(missing)}."], ENGINE_VERSION, r.rule_version)

    on_hand, par, mmin = int(inp.on_hand_qty), int(inp.par_level), int(inp.mandatory_minimum)
    lead = int(inp.lead_time_days)
    coverage = lead + r.review_period_days
    rate = max(float(inp.forecast_qty_30d), 0.0) / r.forecast_horizon_days
    upper = inp.forecast_upper_30d if inp.forecast_upper_30d is not None else inp.forecast_qty_30d
    bound_rate = (max(float(upper), 0.0) if r.use_forecast_bound == "upper" else max(float(inp.forecast_qty_30d), 0.0)) / r.forecast_horizon_days
    demand_cov = rate * coverage
    demand_target = bound_rate * coverage
    explanation.append(f"Coverage window = lead time {lead} d + review period {r.review_period_days} d = {coverage} days.")
    explanation.append(f"Forecast demand over the coverage window ≈ {demand_cov:.1f} (upper bound {demand_target:.1f}).")

    if inp.critical_stock_flag:
        event = float(inp.max_weekly_demand_hist or 0.0)
        if event > demand_target:
            explanation.append(f"Critical product: demand target raised to the largest historical single-week "
                               f"demand ({event:.0f}) — recent history alone is not a safe basis for emergency stock.")
            demand_target = event
        policy.append("Critical-stock product: forecasts cannot reduce stock below the approved mandatory minimum.")
    if inp.approved_stocking_policy:
        policy.append(f"Approved stocking policy: {inp.approved_stocking_policy}.")

    if mmin > par:
        factors.append("POLICY_CONFLICT_MIN_ABOVE_PAR")
        policy.append(f"Mandatory minimum ({mmin}) exceeds PAR ({par}); minimum takes precedence pending policy review.")
    target = max(mmin, min(par, math.ceil(demand_target)))
    if demand_target > par:
        factors.append("DEMAND_EXCEEDS_PAR")
        policy.append(f"Forecast-based need ({demand_target:.0f}) exceeds PAR ({par}); target capped at PAR — consider a PAR review.")
    if target == mmin and math.ceil(demand_target) < mmin:
        explanation.append(f"Mandatory minimum ({mmin}) sets the target: forecast need ({demand_target:.1f}) is lower.")
    elif target == par:
        explanation.append(f"Target capped at PAR ({par}).")
    else:
        explanation.append(f"Target inventory = forecast-based need {target} (between minimum {mmin} and PAR {par}).")

    # stock that expires before the next replenishment could land cannot cover demand in this window
    expiring_in_window = int(sum(l.qty for l in inp.lots if l.days_to_expiry <= coverage))
    usable = max(0.0, on_hand - expiring_in_window)
    effective = usable + int(inp.pending_inbound_qty or 0)
    if expiring_in_window:
        explanation.append(f"{expiring_in_window} of {on_hand} on hand expire within the {coverage}-day coverage "
                           f"window and are excluded from usable stock.")
    # expiry RISK: near-expiry lots projected (FEFO, forecast rate) to still be on hand when they expire
    near_lots = [l for l in inp.lots if l.days_to_expiry <= r.near_expiry_days]
    near_qty = int(sum(l.qty for l in near_lots))
    unused = project_expiring_unused(near_lots, rate)
    if unused >= 0.5:
        explanation.append(f"{unused:.0f} of the {near_qty} units expiring within {r.near_expiry_days} days are "
                           f"projected to expire unused at the forecast usage rate.")
    if inp.pending_inbound_qty:
        explanation.append(f"{inp.pending_inbound_qty} units already in transit are counted as available.")

    rec = round_up_to_pack(max(0.0, target - effective), inp.pack_size)
    explanation.append(f"Recommended = max(0, target {target} − effective available {effective:.0f}) rounded up to "
                       f"pack size {inp.pack_size} = {rec}.")
    explanation.append(f"Simplified PAR-only baseline (PAR − on hand) would be {par_base}; the engine also applies "
                       f"forecast demand, minimum stock, expiry, in-transit and pack constraints.")

    req = inp.requested_qty
    excess = max(0, int(req) - rec) if req is not None else 0
    exposure = round(excess * float(inp.unit_cost), 2)
    cover_days = None
    excessive = stockout = False
    if req is not None:
        cover_days = (effective + req) / rate if rate > 0 else float("inf")
        excessive = req > max(rec * r.ratio_threshold, rec + r.abs_threshold_units)
        if not inp.critical_stock_flag:
            # cover-days is meaningless for emergency stock held for rare events, so it only applies to
            # non-critical products
            excessive = excessive or (req > rec and cover_days > r.max_cover_days)
        stockout = req < rec and (effective + req) < max(mmin, demand_cov * r.min_cover_ratio)
        if excessive:
            factors.append("EXCESSIVE_REQUEST")
            cd = "no forecast demand" if cover_days == float("inf") else f"~{cover_days:,.0f} days of forecast demand"
            explanation.append(f"Request of {req} is {req - rec} above the recommendation and would leave {cd} on hand.")
        if stockout:
            factors.append("UNDER_SIZED_REQUEST")
            explanation.append(f"Request of {req} would leave {effective + req:.0f} units against ~{max(mmin, demand_cov):.0f} "
                               f"needed before the next replenishment — stockout risk.")
    else:
        if effective < max(mmin, demand_cov):
            stockout = True
            factors.append("BELOW_COVERAGE")

    unused_value = unused * float(inp.unit_cost)
    expiry = unused >= 1 and (unused_value >= r.expiry_risk_value_threshold or
                              (on_hand > 0 and unused / on_hand >= r.expiry_risk_share_threshold))
    if expiry:
        factors.append("EXPIRY_RISK")
        explanation.append(f"Projected unused expiring stock ≈ ${unused_value:,.0f}; consider rebalancing or return options.")
    critical_hold = bool(inp.critical_stock_flag and on_hand < mmin)
    if critical_hold:
        factors.append("CRITICAL_POLICY_HOLD")
    if on_hand < mmin:
        factors.append("BELOW_MANDATORY_MINIMUM")
    high_returns = inp.returns_count_12m >= r.high_returns_count_12m or inp.returns_cost_12m >= r.high_returns_cost_12m
    if high_returns:
        factors.append("HIGH_RETURNS_HISTORY")
        explanation.append(f"Site returned this SKU {inp.returns_count_12m} times in 12 months "
                           f"(cold-chain logistics ≈ ${inp.returns_cost_12m:,.0f}).")
    if inp.consumption_last_120d is not None:
        explanation.append(f"Actual consumption in the last 120 days: {inp.consumption_last_120d:.0f}.")

    if excessive:
        cat = "EXCESSIVE_REQUEST"
    elif stockout:
        cat = "STOCKOUT_RISK"
    elif expiry:
        cat = "EXPIRY_RISK"
    elif critical_hold:
        cat = "CRITICAL_POLICY_HOLD"
    else:
        cat = "WITHIN_POLICY"

    reasons = []
    if excessive:
        reasons.append(f"request exceeds recommendation by {excess} units (${exposure:,.0f} potential exposure)")
    if stockout:
        reasons.append("request may not cover demand until next replenishment")
    if expiry:
        reasons.append("short-dated stock projected to expire unused")
    if inp.critical_stock_flag and r.critical_products_always_review and (req is None or req != rec or critical_hold):
        reasons.append("critical-stock product — policy requires human review")
    if inp.policy_review_required:
        reasons.append("stocking policy flags this SKU for review")
    if exposure >= r.high_exposure_value_threshold:
        reasons.append("exposure above review threshold")
    if high_returns and req is not None and req > rec:
        reasons.append("high returns history")
    review = bool(reasons)
    review_reason = ("; ".join(reasons)).capitalize() if reasons else "Within configured policy; no mandatory review."

    return Recommendation(
        inp.customer_id, inp.sku, req, rec, par_base, int(target), round(effective, 2), round(usable, 2),
        round(unused, 2), near_qty, coverage, round(demand_cov, 3), round(demand_target, 3), int(excess), exposure,
        (None if cover_days is None else (round(cover_days, 1) if cover_days != float("inf") else None)),
        cat, factors, policy, [], review, review_reason, explanation, ENGINE_VERSION, r.rule_version)

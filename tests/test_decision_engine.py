"""Unit tests for the deterministic replenishment decision engine (stdlib only)."""
import pytest

from src.optimization.engine import EngineRules, LotPosition, RecommendationInput, recommend, round_up_to_pack

R = EngineRules()


def hospital_a(**kw):
    base = dict(customer_id="CUST-001", sku="SKU-1001", requested_qty=500, on_hand_qty=25, par_level=60,
                mandatory_minimum=40, lead_time_days=3, forecast_qty_30d=0.7, forecast_upper_30d=2.2,
                pack_size=5, unit_cost=900.0, critical_stock_flag=True, policy_review_required=True,
                approved_stocking_policy="CRITICAL_MINIMUM_HOLD", max_weekly_demand_hist=3,
                lots=[LotPosition("L1", 25, 400)], consumption_last_120d=1)
    base.update(kw)
    return RecommendationInput(**base)


def test_500_dose_request_is_flagged_excessive():
    out = recommend(hospital_a(), R)
    assert out.risk_category == "EXCESSIVE_REQUEST"
    assert out.human_review_required
    assert out.par_only_baseline_qty == 35
    assert out.recommended_qty == 15                     # min 40 - 25 on hand, pack 5 — not the PAR-only 35
    assert out.excess_qty == 485 and out.potential_exposure_value == 485 * 900


def test_forecast_never_overrides_mandatory_minimum():
    out = recommend(hospital_a(forecast_qty_30d=0.0, forecast_upper_30d=0.0, max_weekly_demand_hist=0,
                               requested_qty=None), R)
    assert out.target_inventory >= 40
    assert out.recommended_qty == 15


def test_target_capped_at_par_and_flagged():
    out = recommend(hospital_a(critical_stock_flag=False, forecast_qty_30d=900, forecast_upper_30d=1000,
                               requested_qty=None), R)
    assert out.target_inventory == 60
    assert "DEMAND_EXCEEDS_PAR" in out.risk_factors


def test_under_sized_request_is_stockout_risk():
    inp = RecommendationInput("C", "S", 10, 6, 90, 30, 2, 87.0, 101.0, pack_size=1, unit_cost=1180.0,
                              lots=[LotPosition("L", 6, 300)])
    out = recommend(inp, R)
    assert out.risk_category == "STOCKOUT_RISK" and out.recommended_qty > 10 and out.human_review_required


def test_short_dated_stock_is_expiry_risk():
    inp = RecommendationInput("C", "S", 2, 22, 16, 6, 2, 4.0, 6.9, pack_size=1, unit_cost=2400.0,
                              lots=[LotPosition("short", 14, 38), LotPosition("long", 8, 500)])
    out = recommend(inp, R)
    assert out.risk_category == "EXPIRY_RISK"
    assert out.projected_expiring_unused_qty == pytest.approx(14 - 4.0 / 30 * 38, abs=0.01)


def test_critical_below_minimum_is_policy_hold_and_requires_review():
    inp = RecommendationInput("C", "S", 4, 6, 12, 8, 3, 0.9, 3.0, pack_size=1, unit_cost=3200.0,
                              critical_stock_flag=True, max_weekly_demand_hist=7, lots=[LotPosition("L", 6, 700)])
    out = recommend(inp, R)
    assert out.risk_category == "CRITICAL_POLICY_HOLD" and out.recommended_qty == 2 and out.human_review_required


def test_in_transit_counts_as_available():
    a = recommend(hospital_a(requested_qty=None), R).recommended_qty
    b = recommend(hospital_a(requested_qty=None, pending_inbound_qty=10), R).recommended_qty
    assert b == a - 10


def test_lots_expiring_inside_coverage_are_not_usable():
    out = recommend(hospital_a(requested_qty=None, lots=[LotPosition("a", 20, 5), LotPosition("b", 5, 400)]), R)
    assert out.usable_on_hand_qty == 5 and out.recommended_qty == 35


@pytest.mark.parametrize("field", ["on_hand_qty", "par_level", "mandatory_minimum", "forecast_qty_30d", "lead_time_days"])
def test_missing_data_blocks_quantity_and_requires_review(field):
    out = recommend(hospital_a(**{field: None}), R)
    assert out.recommended_qty is None and out.risk_category == "MISSING_DATA" and out.human_review_required
    assert field.replace("_30d", "").replace("forecast_qty", "forecast") in out.missing_information


def test_pack_rounding():
    assert round_up_to_pack(11, 5) == 15 and round_up_to_pack(0, 5) == 0 and round_up_to_pack(10, 5) == 10


def test_within_policy_request_needs_no_review():
    inp = RecommendationInput("C", "S", 20, 10, 60, 20, 2, 60.0, 70.0, pack_size=10, unit_cost=100.0,
                              lots=[LotPosition("L", 10, 400)])
    out = recommend(inp, R)
    assert out.risk_category == "WITHIN_POLICY" and not out.human_review_required


def test_engine_is_deterministic():
    assert recommend(hospital_a(), R).to_dict() == recommend(hospital_a(), R).to_dict()


def test_rules_load_from_config(rules_cfg):
    r = EngineRules.from_config(rules_cfg)
    assert r.ratio_threshold == 2.0 and r.review_period_days == 7

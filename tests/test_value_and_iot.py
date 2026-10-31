"""Financial calculation consistency, no double counting, and IoT detector behaviour."""
import numpy as np
import pandas as pd

from src.iot.anomaly import score
from src.value.simulator import ValueAssumptions, ValueBaseline, simulate

BASE = ValueBaseline(excess_on_hand_value=500000, near_expiry_value=90000, expired_value_12m=80000,
                     avoidable_returns_count_12m=200, avoidable_return_logistics_12m=90000, unmet_units_12m=100,
                     avg_margin_per_unit=60)


def test_value_components_are_separate_and_consistent():
    r = simulate(BASE, ValueAssumptions())
    assert r.total_annual_cost_avoidance == round(r.returns_logistics_avoided + r.expiry_losses_avoided +
                                                  r.carrying_cost_avoided + r.availability_margin_protected, 2)
    # inventory released is a one-time balance-sheet effect: never part of annual benefit
    assert r.total_annual_cost_avoidance < r.inventory_value_released + r.total_annual_cost_avoidance
    assert r.net_annual_benefit == round(r.total_annual_cost_avoidance - r.annual_solution_cost, 2)
    assert r.realized_cash_savings is None and "ILLUSTRATIVE" in r.label


def test_zero_avoidable_means_zero_excess_benefit():
    r = simulate(BASE, ValueAssumptions(avoidable_excess_pct=0.0))
    assert r.inventory_value_released == 0 and r.returns_logistics_avoided == 0 and r.carrying_cost_avoided == 0


def test_benefit_scales_linearly_and_is_bounded():
    a = simulate(BASE, ValueAssumptions(avoidable_excess_pct=0.2))
    b = simulate(BASE, ValueAssumptions(avoidable_excess_pct=0.4))
    assert abs(b.inventory_value_released - 2 * a.inventory_value_released) < 0.01
    c = simulate(BASE, ValueAssumptions(avoidable_excess_pct=5.0))      # clamped to 100%
    assert c.inventory_value_released == BASE.excess_on_hand_value


def test_iot_detector_flags_only_planted_device(tables):
    s = score(tables["device_telemetry"])
    flagged = set(s[s.is_anomaly].device_id)
    assert flagged == {"RNI-DEV-0701"}
    assert s.anomaly_score.between(0, 1).all()


def test_iot_detector_quiet_on_stable_signal():
    ts = pd.date_range("2026-10-01", periods=2880, freq="15min")
    rng = np.random.default_rng(0)
    df = pd.DataFrame(dict(device_id="D", customer_id="C", event_timestamp=ts, temperature_c=5 + rng.normal(0, .15, 2880),
                           vibration_mm_s=1.8 + rng.normal(0, .12, 2880), compressor_status="RUNNING"))
    assert not score(df).is_anomaly.any()

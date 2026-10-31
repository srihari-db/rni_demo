"""Automated data-quality tests for the synthetic RNI dataset (local regeneration and live Unity Catalog)."""
import datetime as dt
import json

import pandas as pd
import pytest

from conftest import CATALOG, LIVE
from src.data import quality


def _assert_all(results):
    failed = [r for r in results if not r.passed]
    assert not failed, "\n".join(f"{r.name}: {r.detail}" for r in failed)


def test_every_transaction_references_valid_customer_and_sku(tables):
    _assert_all([r for r in quality.check_referential_integrity(tables)])


def test_no_negative_inventory_and_ledger_reconciles(tables):
    _assert_all(quality.check_inventory(tables))


def test_returns_do_not_exceed_eligible_inventory(tables):
    _assert_all(quality.check_returns(tables))


def test_shipment_lifecycle_states_valid(tables, snapshot):
    _assert_all(quality.check_order_lifecycle(tables, snapshot))


def test_executive_scenarios_staged(tables, cfg):
    _assert_all(quality.check_scenarios(tables, cfg))


def test_hospital_a_scenario_exact(tables, snapshot):
    pos = tables["inventory_positions"]
    cur = pos[(pd.to_datetime(pos.snapshot_date).dt.date == snapshot) & (pos.customer_id == "CUST-001") & (pos.sku == "SKU-1001")]
    assert int(cur.on_hand_qty.sum()) == 25
    par = tables["par_levels"].set_index(["customer_id", "sku"]).loc[("CUST-001", "SKU-1001")]
    assert (int(par.par_level), int(par.mandatory_minimum)) == (60, 40)
    u = tables["usage_history"]
    u = u[(u.customer_id == "CUST-001") & (u.sku == "SKU-1001") & (pd.to_datetime(u.usage_date).dt.date > snapshot - dt.timedelta(days=120))]
    assert int(u.quantity_consumed.sum()) == 1
    assert float(tables["product_master"].set_index("sku").loc["SKU-1001", "unit_cost"]) == 900.0
    names = tables["customer_master"].set_index("customer_id").customer_name
    assert names["CUST-001"] == "Hospital A"
    assert tables["product_master"].set_index("sku").loc["SKU-1001", "product_name"].startswith("Product A")
    so = tables["shipment_orders"]
    req = so[(so.scenario_id == "SCN-01") & (so.order_status == "PENDING_REVIEW")]
    assert len(req) == 1 and int(req.requested_qty.iloc[0]) == 500


def test_distinguishes_movement_from_utilization(tables):
    ev = tables["inventory_events"]
    received = ev[ev.event_type == "RECEIPT"].quantity_delta.sum()
    consumed = -ev[ev.event_type == "CONSUMPTION"].quantity_delta.sum()
    returned = -ev[ev.event_type == "RETURN"].quantity_delta.sum()
    assert received > consumed > 0 and returned > 0      # not every shipped unit is consumed


def test_regeneration_is_deterministic(cfg):
    from src.data.simulator import simulate
    a, b = simulate(cfg), simulate(cfg)
    for k in ["usage_history", "shipment_orders", "return_orders", "inventory_events"]:
        pd.testing.assert_frame_equal(a[k], b[k])


def test_no_phi_like_columns(tables):
    banned = {"patient", "mrn", "dob", "ssn", "diagnosis", "dose_mg_per_kg"}
    for name, df in tables.items():
        assert not banned.intersection(c.lower() for c in df.columns), name


# ------------------------------------------------------------------------------------- live Unity Catalog checks
def _q(spark, sql):
    return spark.sql(sql.replace("{c}", CATALOG)).toPandas()


def test_live_recommendations_agree_with_engine(spark, rules_cfg):
    from src.optimization.batch import input_from_json
    from src.optimization.engine import EngineRules, recommend
    rules = EngineRules.from_config(rules_cfg)
    recs = _q(spark, "SELECT recommendation_id, recommended_qty, risk_category, human_review_required, engine_input "
                     "FROM {c}.ml.replenishment_recommendations")
    assert len(recs) > 0
    bad = []
    for r in recs.itertuples():
        out = recommend(input_from_json(r.engine_input), rules)
        exp_qty = None if pd.isna(r.recommended_qty) else int(r.recommended_qty)
        if (out.recommended_qty, out.risk_category, out.human_review_required) != (exp_qty, r.risk_category, bool(r.human_review_required)):
            bad.append(r.recommendation_id)
    assert not bad, f"{len(bad)} stored recommendations differ from the engine, e.g. {bad[:5]}"


def test_live_forecasts_do_not_use_future_observations(spark, snapshot):
    f = _q(spark, "SELECT training_cutoff_date, training_obs_max_date, forecast_date, lower_bound, predicted_demand, upper_bound "
                  "FROM {c}.ml.demand_forecasts")
    assert len(f) > 0
    assert (pd.to_datetime(f.training_obs_max_date) <= pd.to_datetime(f.training_cutoff_date)).all()
    assert (pd.to_datetime(f.forecast_date).dt.date == snapshot).all()
    assert ((f.lower_bound <= f.predicted_demand + 1e-6) & (f.predicted_demand <= f.upper_bound + 1e-6)).all()


def test_live_financial_kpis_reconcile_to_source(spark):
    k = _q(spark, "SELECT * FROM {c}.gold.kpi_executive").iloc[0]
    inv = _q(spark, "SELECT SUM(p.on_hand_qty * pr.unit_cost) v FROM {c}.silver.inventory_positions p "
                    "JOIN {c}.silver.product_master pr USING (sku) WHERE p.is_current").v.iloc[0]
    assert abs(k.total_inventory_deployed_value - inv) < 0.01
    ret = _q(spark, "SELECT SUM(r.returned_value) v FROM {c}.silver.return_orders r, {c}.gold.as_of a "
                    "WHERE r.return_date > date_sub(a.as_of_date, 365)").v.iloc[0]
    assert abs(k.returns_value_12m - ret) < 0.01
    exp = _q(spark, "SELECT SUM(potential_exposure_value) v FROM {c}.gold.shipment_review_queue").v.iloc[0]
    assert abs(k.pending_request_exposure_value - exp) < 0.01
    rv = _q(spark, "SELECT SUM(CASE WHEN human_review_required THEN 1 ELSE 0 END) n FROM {c}.gold.shipment_review_queue").n.iloc[0]
    assert int(k.shipment_requests_requiring_review) == int(rv)


def test_live_exposure_buckets_do_not_double_count(spark):
    e = _q(spark, "SELECT * FROM {c}.gold.inventory_exposure_current")
    assert (e.near_expiry_qty + e.excess_qty + e.healthy_qty == e.on_hand_qty).all()
    assert ((e.near_expiry_qty >= 0) & (e.excess_qty >= 0) & (e.healthy_qty >= 0)).all()
    assert abs((e.near_expiry_value + e.excess_value + e.healthy_value).sum() - e.inventory_value.sum()) < 0.01


def test_live_ledger_reconciles_in_unity_catalog(spark):
    d = _q(spark, """
        WITH l AS (SELECT customer_id, sku, lot_id, SUM(quantity_delta) q FROM {c}.silver.inventory_events GROUP BY ALL),
             p AS (SELECT customer_id, sku, lot_id, on_hand_qty q FROM {c}.silver.inventory_positions WHERE is_current)
        SELECT COUNT(*) n FROM l FULL OUTER JOIN p USING (customer_id, sku, lot_id)
        WHERE COALESCE(l.q, 0) <> COALESCE(p.q, 0)""")
    assert int(d.n.iloc[0]) == 0


def test_live_hospital_a_flagged(spark):
    r = _q(spark, "SELECT * FROM {c}.gold.shipment_review_queue WHERE scenario_id = 'SCN-01'").iloc[0]
    assert r.requested_qty == 500 and r.risk_category == "EXCESSIVE_REQUEST" and bool(r.human_review_required)
    assert r.par_only_baseline_qty == 35 and r.recommended_qty != 35

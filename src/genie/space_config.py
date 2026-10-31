"""Definition of the 'RNI Inventory Intelligence Agent' Genie space: approved Gold tables, business definitions,
verified example SQL and benchmark questions. Used by scripts/setup_genie.py and by tests."""
from __future__ import annotations

import hashlib

SPACE_TITLE = "RNI Inventory Intelligence Agent"
SPACE_DESCRIPTION = (
    "Ask about FFF Right Now Inventory (RNI) customer-site inventory, PAR, consumption, shipment requests, returns, "
    "expiration risk, demand forecasts and decision-engine recommendations. ALL DATA IS SYNTHETIC (demo)."
)

GENIE_TABLES = [
    "dim_customer", "dim_product", "inventory_exposure_current", "inventory_lots_current", "expiry_risk_horizon",
    "consumption_vs_shipments_monthly", "returns_detail", "demand_forecasts", "replenishment_recommendations",
    "shipment_review_queue", "inventory_value_metrics", "kpi_executive",
]

BUSINESS_DEFINITIONS = """
You are the RNI Inventory Intelligence Agent for FFF Enterprises' Right Now Inventory (RNI) business. All data is
synthetic demo data; dollar values are illustrative.

Business definitions:
- PAR: contracted target stock level for a customer location and SKU (par_level).
- Mandatory minimum: approved minimum stock that must be held regardless of forecast (mandatory_minimum).
- On-hand inventory: units physically in the RNI device at the snapshot (on_hand_qty); value = on_hand_qty x unit_cost.
- Shipped quantity: units shipped/received from FFF (product MOVEMENT). Shipments are NOT consumption.
- Consumption: units dispensed for use at the site (product UTILIZATION, consumed_qty).
- Return rate: returned units / shipped units over the same period (use consumption_vs_shipments_monthly).
- Excess inventory: on-hand units above PAR that are not near expiry (excess_qty / excess_value).
- Expiration risk: inventory in lots expiring within 90 days (near_expiry_value); horizons in expiry_risk_horizon.
- Inventory exposure: excess on hand + potential exposure of pending flagged requests (potential_excess_exposure_value).
  This is POTENTIAL exposure, never realized savings.
- Forecast demand: predicted_demand from demand_forecasts for a 30/60/90-day horizon with an 80% interval.
- Recommended quantity: deterministic decision-engine output (recommended_qty). Never invent or change quantities.
- "Last 12 months" is relative to the demo as-of date (as_of_date in kpi_executive), NOT current_date().

Rules:
- Excess, near-expiry and healthy buckets are mutually exclusive; never add near_expiry_value and excess_value to
  inventory_value.
- To explain why a request was flagged, use shipment_review_queue (review_reason, risk_category, requested_qty,
  recommended_qty, consumed_last_120d, potential_exposure_value).
- Hospital A is customer_id CUST-001; Product A is sku SKU-1001.
- Present currency as USD and label results as synthetic.
- Do not provide clinical or dosing advice; stocking levels for emergency products follow approved policy and human review.
"""

# Verified example SQL — every statement is executed and checked by scripts/setup_genie.py before upload.
EXAMPLE_SQL = [
    ("Which customers have the highest excess inventory exposure?",
     """SELECT customer_name, region, ROUND(SUM(potential_excess_exposure_value), 0) AS potential_excess_exposure_usd,
       ROUND(SUM(potential_excess_value), 0) AS excess_on_hand_usd, ROUND(SUM(pending_request_exposure_value), 0) AS pending_request_exposure_usd
FROM {g}.inventory_value_metrics GROUP BY customer_name, region ORDER BY potential_excess_exposure_usd DESC LIMIT 10"""),
    ("Which products have the highest return rates?",
     """SELECT product_name, product_category, SUM(returned_qty) AS returned_units, SUM(shipped_qty) AS shipped_units,
       ROUND(SUM(returned_qty) / NULLIF(SUM(shipped_qty), 0), 3) AS return_rate
FROM {g}.consumption_vs_shipments_monthly
WHERE month > ADD_MONTHS((SELECT as_of_date FROM {g}.kpi_executive), -12)
GROUP BY product_name, product_category HAVING SUM(shipped_qty) > 0 ORDER BY return_rate DESC LIMIT 10"""),
    ("Why was Hospital A's shipment request flagged?",
     """SELECT customer_name, product_name, requested_qty, recommended_qty, par_only_baseline_qty, on_hand_qty, par_level,
       mandatory_minimum, consumed_last_120d, ROUND(forecast_30d_qty, 2) AS forecast_30d_qty, risk_category,
       ROUND(potential_exposure_value, 0) AS potential_exposure_usd, review_reason
FROM {g}.shipment_review_queue WHERE customer_id = 'CUST-001'"""),
    ("Which products may expire in the next 60 days?",
     """SELECT customer_name, product_name, lot_id, expiry_date, days_to_expiry, on_hand_qty, ROUND(inventory_value, 0) AS inventory_value_usd
FROM {g}.inventory_lots_current WHERE days_to_expiry <= 60 ORDER BY inventory_value DESC"""),
    ("Which customers have the highest shipments relative to usage?",
     """SELECT customer_name, region, SUM(shipped_qty) AS shipped_units, SUM(consumed_qty) AS consumed_units,
       ROUND(SUM(shipped_value), 0) AS shipped_value_usd, ROUND(SUM(consumed_value), 0) AS consumed_value_usd,
       ROUND(SUM(shipped_value) / NULLIF(SUM(consumed_value), 0), 2) AS shipped_to_consumed_value_ratio
FROM {g}.consumption_vs_shipments_monthly
WHERE month > ADD_MONTHS((SELECT as_of_date FROM {g}.kpi_executive), -12)
GROUP BY customer_name, region ORDER BY shipped_to_consumed_value_ratio DESC LIMIT 10"""),
    ("How much was returned during the last 12 months?",
     """SELECT COUNT(*) AS returns, SUM(returned_qty) AS returned_units, ROUND(SUM(returned_value), 0) AS returned_value_usd,
       ROUND(SUM(return_logistics_cost), 0) AS return_logistics_cost_usd
FROM {g}.returns_detail WHERE in_last_12_months"""),
    ("Which shipment requests need review and what is the potential exposure?",
     """SELECT review_priority, customer_name, product_name, requested_qty, recommended_qty, risk_category,
       ROUND(potential_exposure_value, 0) AS potential_exposure_usd, review_reason
FROM {g}.shipment_review_queue WHERE human_review_required ORDER BY review_priority"""),
    ("What is our total inventory deployed and how much is approaching expiration?",
     """SELECT ROUND(total_inventory_deployed_value, 0) AS total_inventory_deployed_usd,
       ROUND(inventory_approaching_expiration_value, 0) AS approaching_expiration_usd,
       ROUND(potential_excess_exposure_value, 0) AS potential_excess_exposure_usd, as_of_date
FROM {g}.kpi_executive"""),
]

SAMPLE_QUESTIONS = [q for q, _ in EXAMPLE_SQL[:7]]

BENCHMARKS = EXAMPLE_SQL  # benchmark question -> expected (verified) SQL answer


def stable_id(*parts: str) -> str:
    """32-hex id required by the Genie serialized-space format (deterministic for idempotent updates)."""
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def serialized_space(catalog: str) -> dict:
    g = f"{catalog}.gold"
    tables = sorted(f"{g}.{t}" for t in GENIE_TABLES)
    return {
        "version": 2,
        "config": {"sample_questions": sorted(
            [{"id": stable_id("sq", q), "question": [q]} for q in SAMPLE_QUESTIONS], key=lambda x: x["id"])},
        "data_sources": {"tables": [{"identifier": t} for t in tables]},
        "instructions": {
            "text_instructions": [{"id": stable_id("ti", "defs"), "content": [BUSINESS_DEFINITIONS.strip()]}],
            "example_question_sqls": sorted(
                [{"id": stable_id("eq", q), "question": [q], "sql": [s.format(g=g)]} for q, s in EXAMPLE_SQL],
                key=lambda x: x["id"]),
        },
        "benchmarks": {"questions": sorted(
            [{"id": stable_id("bm", q), "question": [q], "answer": [{"format": "SQL", "content": [s.format(g=g)]}]}
             for q, s in BENCHMARKS], key=lambda x: x["id"])},
    }

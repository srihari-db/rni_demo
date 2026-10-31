-- =====================================================================================================
-- RNI Intelligent Operations Command Center — Gold layer (single source of business definitions)
-- Shared by the AI/BI Dashboard, the Databricks App and the Genie agent. {{catalog}} is substituted.
-- All dollar values are SYNTHETIC and ILLUSTRATIVE.
--
-- Inventory risk buckets are MUTUALLY EXCLUSIVE per customer/SKU so they can be summed without double counting:
--   near_expiry_qty  = units in lots expiring within 90 days of the snapshot
--   excess_qty       = units above PAR that are NOT near expiry   = LEAST(on_hand - near_expiry, GREATEST(0, on_hand - PAR))
--   healthy_qty      = on_hand - near_expiry_qty - excess_qty
-- =====================================================================================================

CREATE OR REPLACE VIEW {{catalog}}.gold.as_of
COMMENT 'Demo as-of date: the current inventory snapshot date. All "last 12 months" metrics are relative to this date.'
AS SELECT MAX(snapshot_date) AS as_of_date FROM {{catalog}}.silver.inventory_positions WHERE is_current;

CREATE OR REPLACE VIEW {{catalog}}.gold.dim_customer
COMMENT 'RNI customer locations (synthetic).'
AS SELECT customer_id, customer_name, location, customer_type, region FROM {{catalog}}.silver.customer_master;

CREATE OR REPLACE VIEW {{catalog}}.gold.dim_product
COMMENT 'RNI products (synthetic, fictional names). unit_cost is the synthetic inventory value per unit.'
AS SELECT sku, product_name, product_category, unit_cost, selling_price, shelf_life_days, storage_type,
          critical_stock_flag, pack_size, unit_of_measure, cold_chain_required
   FROM {{catalog}}.silver.product_master;

-- ------------------------------------------------------------------------------------------- inventory
CREATE OR REPLACE VIEW {{catalog}}.gold.inventory_lots_current
COMMENT 'Current on-hand inventory by customer/device/SKU/lot with value and days to expiry. expiry_horizon buckets: 0-30, 31-60, 61-90, 91-180, 181-365, >365 days.'
AS
SELECT p.customer_id, c.customer_name, c.region, c.customer_type, p.device_id, p.sku, pr.product_name,
       pr.product_category, pr.critical_stock_flag, p.lot_id, p.on_hand_qty, p.expiry_date, p.snapshot_date,
       DATEDIFF(p.expiry_date, p.snapshot_date) AS days_to_expiry,
       CASE WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 30 THEN '0-30 days'
            WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 60 THEN '31-60 days'
            WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 90 THEN '61-90 days'
            WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 180 THEN '91-180 days'
            WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 365 THEN '181-365 days'
            ELSE '>365 days' END AS expiry_horizon,
       CASE WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 30 THEN 1
            WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 60 THEN 2
            WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 90 THEN 3
            WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 180 THEN 4
            WHEN DATEDIFF(p.expiry_date, p.snapshot_date) <= 365 THEN 5 ELSE 6 END AS expiry_horizon_order,
       pr.unit_cost, p.on_hand_qty * pr.unit_cost AS inventory_value
FROM {{catalog}}.silver.inventory_positions p
JOIN {{catalog}}.silver.customer_master c USING (customer_id)
JOIN {{catalog}}.silver.product_master pr USING (sku)
WHERE p.is_current;

CREATE OR REPLACE VIEW {{catalog}}.gold.inventory_exposure_current
COMMENT 'Current inventory per customer/SKU split into mutually exclusive buckets (near-expiry, excess above PAR, healthy) with synthetic USD values. Sum freely without double counting.'
AS
WITH lots AS (
  SELECT customer_id, sku, SUM(on_hand_qty) AS on_hand_qty,
         SUM(CASE WHEN days_to_expiry <= 90 THEN on_hand_qty ELSE 0 END) AS near_expiry_qty
  FROM {{catalog}}.gold.inventory_lots_current GROUP BY customer_id, sku
), base AS (
  SELECT a.customer_id, a.sku, COALESCE(l.on_hand_qty, 0) AS on_hand_qty, COALESCE(l.near_expiry_qty, 0) AS near_expiry_qty,
         pl.par_level, pl.mandatory_minimum, a.scenario_id
  FROM {{catalog}}.silver.customer_product_assignments a
  JOIN {{catalog}}.silver.par_levels pl USING (customer_id, sku)
  LEFT JOIN lots l USING (customer_id, sku)
)
SELECT b.customer_id, c.customer_name, c.region, c.customer_type, b.sku, pr.product_name, pr.product_category,
       pr.critical_stock_flag, pr.storage_type, pr.unit_cost, b.par_level, b.mandatory_minimum, b.scenario_id,
       b.on_hand_qty, b.near_expiry_qty,
       LEAST(b.on_hand_qty - b.near_expiry_qty, GREATEST(0, b.on_hand_qty - b.par_level)) AS excess_qty,
       b.on_hand_qty - b.near_expiry_qty - LEAST(b.on_hand_qty - b.near_expiry_qty, GREATEST(0, b.on_hand_qty - b.par_level)) AS healthy_qty,
       b.on_hand_qty * pr.unit_cost AS inventory_value,
       b.near_expiry_qty * pr.unit_cost AS near_expiry_value,
       LEAST(b.on_hand_qty - b.near_expiry_qty, GREATEST(0, b.on_hand_qty - b.par_level)) * pr.unit_cost AS excess_value,
       (b.on_hand_qty - b.near_expiry_qty - LEAST(b.on_hand_qty - b.near_expiry_qty, GREATEST(0, b.on_hand_qty - b.par_level))) * pr.unit_cost AS healthy_value,
       CASE WHEN b.on_hand_qty < b.mandatory_minimum THEN 'BELOW_MINIMUM'
            WHEN b.near_expiry_qty > 0 THEN 'NEAR_EXPIRY'
            WHEN b.on_hand_qty > b.par_level THEN 'ABOVE_PAR'
            ELSE 'WITHIN_POLICY' END AS stock_status
FROM base b
JOIN {{catalog}}.silver.customer_master c USING (customer_id)
JOIN {{catalog}}.silver.product_master pr USING (sku);

CREATE OR REPLACE VIEW {{catalog}}.gold.expiry_risk_horizon
COMMENT 'Current inventory value by time-to-expiry horizon (lot level).'
AS SELECT region, customer_id, customer_name, product_category, sku, product_name, expiry_horizon, expiry_horizon_order,
          SUM(on_hand_qty) AS on_hand_qty, SUM(inventory_value) AS inventory_value
   FROM {{catalog}}.gold.inventory_lots_current
   GROUP BY ALL;

-- ------------------------------------------------------------------------------------------- movement vs utilization
CREATE OR REPLACE VIEW {{catalog}}.gold.consumption_vs_shipments_monthly
COMMENT 'Monthly product utilization (consumption) versus product movement (shipments received, returns, expiry disposal) per customer/SKU. Shipments are not consumption.'
AS
WITH ev AS (
  SELECT customer_id, sku, DATE_TRUNC('MONTH', event_date) AS month,
         SUM(CASE WHEN event_type = 'CONSUMPTION' THEN -quantity_delta ELSE 0 END) AS consumed_qty,
         SUM(CASE WHEN event_type = 'RECEIPT' THEN quantity_delta ELSE 0 END) AS received_qty,
         SUM(CASE WHEN event_type = 'RETURN' THEN -quantity_delta ELSE 0 END) AS returned_qty,
         SUM(CASE WHEN event_type = 'EXPIRY_DISPOSAL' THEN -quantity_delta ELSE 0 END) AS expired_qty
  FROM {{catalog}}.silver.inventory_events
  WHERE event_type <> 'OPENING_BALANCE'
  GROUP BY ALL
)
SELECT CAST(e.month AS DATE) AS month, e.customer_id, c.customer_name, c.region, e.sku, pr.product_name, pr.product_category,
       e.consumed_qty, e.received_qty AS shipped_qty, e.returned_qty, e.expired_qty,
       e.consumed_qty * pr.unit_cost AS consumed_value, e.received_qty * pr.unit_cost AS shipped_value,
       e.returned_qty * pr.unit_cost AS returned_value, e.expired_qty * pr.unit_cost AS expired_value
FROM ev e
JOIN {{catalog}}.silver.customer_master c USING (customer_id)
JOIN {{catalog}}.silver.product_master pr USING (sku);

CREATE OR REPLACE VIEW {{catalog}}.gold.usage_weekly
COMMENT 'Weekly consumption per customer/SKU (weeks start Monday) for forecast charts.'
AS SELECT customer_id, sku, CAST(DATE_TRUNC('WEEK', usage_date) AS DATE) AS week_start, SUM(quantity_consumed) AS consumed_qty
   FROM {{catalog}}.silver.usage_history GROUP BY ALL;

-- ------------------------------------------------------------------------------------------- returns
CREATE OR REPLACE VIEW {{catalog}}.gold.returns_detail
COMMENT 'Returns with names, total return logistics cost (shipping + processing) and whether the return was potentially avoidable (driven by over-allocation). Values synthetic.'
AS
SELECT r.return_id, r.return_date, CAST(DATE_TRUNC('MONTH', r.return_date) AS DATE) AS return_month, r.customer_id,
       c.customer_name, c.region, r.sku, pr.product_name, pr.product_category, r.lot_id, r.returned_qty, r.return_reason,
       r.returned_value, r.return_shipping_cost, r.return_processing_cost,
       r.return_shipping_cost + r.return_processing_cost AS return_logistics_cost,
       r.cold_chain_shipment,
       r.return_reason IN ('EXCESS_STOCK', 'STOCK_ROTATION') AS potentially_avoidable,
       r.order_link_type, r.source_order_line_id,
       r.return_date > DATE_SUB((SELECT as_of_date FROM {{catalog}}.gold.as_of), 365) AS in_last_12_months
FROM {{catalog}}.silver.return_orders r
JOIN {{catalog}}.silver.customer_master c USING (customer_id)
JOIN {{catalog}}.silver.product_master pr USING (sku);

-- ------------------------------------------------------------------------------------------- forecasts & recommendations
CREATE OR REPLACE VIEW {{catalog}}.gold.demand_forecasts
COMMENT 'Demand forecasts (30/60/90 days) with 80% intervals, produced by the MLflow-tracked forecasting pipeline.'
AS SELECT f.*, c.customer_name, c.region, pr.product_name, pr.product_category
   FROM {{catalog}}.ml.demand_forecasts f
   JOIN {{catalog}}.silver.customer_master c USING (customer_id)
   JOIN {{catalog}}.silver.product_master pr USING (sku);

CREATE OR REPLACE VIEW {{catalog}}.gold.demand_forecast_weekly
COMMENT 'Weekly forecast path (13 weeks) for charts.'
AS SELECT * FROM {{catalog}}.ml.demand_forecast_weekly;

CREATE OR REPLACE VIEW {{catalog}}.gold.replenishment_recommendations
COMMENT 'Decision-engine recommendations for pending requests (SHIPMENT_REQUEST) and proactive cycle reviews (CYCLE_REVIEW). recommended_qty is deterministic; potential_exposure_value is potential exposure, not realized savings.'
AS SELECT r.recommendation_id, r.recommendation_type, r.order_line_id, r.scenario_id, r.customer_id, c.customer_name,
          c.region, r.sku, pr.product_name, pr.product_category, pr.critical_stock_flag, pr.unit_cost,
          r.requested_qty, r.on_hand_qty, r.pending_inbound_qty, r.par_level, r.mandatory_minimum, r.lead_time_days,
          r.forecast_qty AS forecast_30d_qty, r.forecast_lower AS forecast_30d_lower, r.forecast_upper AS forecast_30d_upper,
          r.recommended_qty, r.par_only_baseline_qty, r.target_inventory, r.effective_available_qty,
          r.projected_expiring_unused_qty, r.near_expiry_qty, r.excess_qty, r.potential_exposure_value,
          r.request_cover_days, r.risk_category, r.risk_factors, r.policy_constraints, r.human_review_required,
          r.review_reason, r.explanation, r.engine_input, r.model_version, r.engine_version, r.rule_version,
          r.snapshot_date, r.created_at
   FROM {{catalog}}.ml.replenishment_recommendations r
   JOIN {{catalog}}.silver.customer_master c USING (customer_id)
   JOIN {{catalog}}.silver.product_master pr USING (sku);

CREATE OR REPLACE VIEW {{catalog}}.gold.shipment_review_queue
COMMENT 'Pending shipment requests with the decision-engine recommendation, potential exposure, 120-day consumption and review priority (1 = highest).'
AS
WITH cons AS (
  SELECT customer_id, sku, SUM(quantity_consumed) AS consumed_last_120d
  FROM {{catalog}}.silver.usage_history
  WHERE usage_date > DATE_SUB((SELECT as_of_date FROM {{catalog}}.gold.as_of), 120)
  GROUP BY ALL
)
SELECT o.order_line_id, o.order_id, o.request_date, o.customer_id, r.customer_name, r.region, o.sku, r.product_name,
       r.product_category, r.critical_stock_flag, o.requested_qty, r.recommended_qty, r.par_only_baseline_qty,
       r.on_hand_qty, r.par_level, r.mandatory_minimum, r.forecast_30d_qty, r.forecast_30d_lower, r.forecast_30d_upper,
       COALESCE(cs.consumed_last_120d, 0) AS consumed_last_120d, r.excess_qty, r.potential_exposure_value,
       r.risk_category, r.human_review_required, r.review_reason, r.scenario_id, r.recommendation_id, r.unit_cost,
       o.requested_qty * r.unit_cost AS requested_value,
       DENSE_RANK() OVER (ORDER BY CASE r.risk_category WHEN 'EXCESSIVE_REQUEST' THEN 1 WHEN 'STOCKOUT_RISK' THEN 2
                                   WHEN 'CRITICAL_POLICY_HOLD' THEN 3 WHEN 'EXPIRY_RISK' THEN 4 WHEN 'MISSING_DATA' THEN 5 ELSE 6 END,
                                   r.potential_exposure_value DESC, o.order_line_id) AS review_priority
FROM {{catalog}}.silver.shipment_orders o
JOIN {{catalog}}.gold.replenishment_recommendations r
  ON r.order_line_id = o.order_line_id AND r.recommendation_type = 'SHIPMENT_REQUEST'
LEFT JOIN cons cs ON cs.customer_id = o.customer_id AND cs.sku = o.sku
WHERE o.order_status = 'PENDING_REVIEW';

-- ------------------------------------------------------------------------------------------- financial metrics
CREATE OR REPLACE TABLE {{catalog}}.gold.inventory_value_metrics
COMMENT 'Inventory exposure and financial KPIs per customer/SKU, derived by SQL from source records (synthetic, illustrative). Buckets are mutually exclusive.'
TBLPROPERTIES ('rni_demo.managed'='true')
AS
WITH ret AS (
  SELECT customer_id, sku, SUM(returned_value) AS returned_value_12m, SUM(return_logistics_cost) AS return_logistics_cost_12m,
         SUM(CASE WHEN potentially_avoidable THEN return_logistics_cost ELSE 0 END) AS avoidable_logistics_cost_12m,
         COUNT(*) AS returns_count_12m
  FROM {{catalog}}.gold.returns_detail WHERE in_last_12_months GROUP BY ALL
), exp AS (
  SELECT customer_id, sku, SUM(expired_value) AS expired_value_12m
  FROM {{catalog}}.gold.consumption_vs_shipments_monthly
  WHERE month > ADD_MONTHS((SELECT as_of_date FROM {{catalog}}.gold.as_of), -12) GROUP BY ALL
), req AS (
  SELECT customer_id, sku, SUM(potential_exposure_value) AS pending_request_exposure_value,
         SUM(CASE WHEN human_review_required THEN 1 ELSE 0 END) AS requests_requiring_review
  FROM {{catalog}}.gold.shipment_review_queue GROUP BY ALL
)
SELECT e.customer_id, e.customer_name, e.region, e.sku, e.product_name, e.product_category,
       e.inventory_value, e.excess_qty AS potential_excess_qty, e.excess_value AS potential_excess_value,
       e.near_expiry_value, e.healthy_value,
       COALESCE(r.returned_value_12m, 0) AS returned_value,
       COALESCE(r.return_logistics_cost_12m, 0) AS return_logistics_cost_12m,
       COALESCE(r.avoidable_logistics_cost_12m, 0) AS avoidable_logistics_cost_12m,
       COALESCE(r.returns_count_12m, 0) AS returns_count_12m,
       COALESCE(x.expired_value_12m, 0) AS expired_value_12m,
       COALESCE(q.pending_request_exposure_value, 0) AS pending_request_exposure_value,
       COALESCE(q.requests_requiring_review, 0) AS requests_requiring_review,
       e.excess_value + COALESCE(q.pending_request_exposure_value, 0) AS potential_excess_exposure_value,
       (SELECT as_of_date FROM {{catalog}}.gold.as_of) AS as_of_date,
       'SYNTHETIC / ILLUSTRATIVE' AS value_basis
FROM {{catalog}}.gold.inventory_exposure_current e
LEFT JOIN ret r USING (customer_id, sku)
LEFT JOIN exp x USING (customer_id, sku)
LEFT JOIN req q USING (customer_id, sku);

CREATE OR REPLACE VIEW {{catalog}}.gold.kpi_executive
COMMENT 'One-row executive KPIs. potential_excess_exposure = excess on hand above PAR + exposure of pending flagged requests (non-overlapping). avoidable logistics = 12-month return logistics cost for over-allocation returns (estimate).'
AS
SELECT (SELECT as_of_date FROM {{catalog}}.gold.as_of) AS as_of_date,
       SUM(inventory_value) AS total_inventory_deployed_value,
       SUM(potential_excess_value) AS excess_on_hand_value,
       SUM(pending_request_exposure_value) AS pending_request_exposure_value,
       SUM(potential_excess_exposure_value) AS potential_excess_exposure_value,
       SUM(near_expiry_value) AS inventory_approaching_expiration_value,
       SUM(requests_requiring_review) AS shipment_requests_requiring_review,
       SUM(returned_value) AS returns_value_12m,
       SUM(avoidable_logistics_cost_12m) AS estimated_avoidable_logistics_cost_12m,
       SUM(return_logistics_cost_12m) AS return_logistics_cost_12m,
       SUM(expired_value_12m) AS expired_value_12m,
       (SELECT COUNT(*) FROM {{catalog}}.gold.returns_detail WHERE in_last_12_months AND potentially_avoidable) AS avoidable_returns_count_12m,
       (SELECT COALESCE(SUM(s.unmet_qty), 0) FROM {{catalog}}.silver.stockout_events s, {{catalog}}.gold.as_of a
         WHERE s.event_date > DATE_SUB(a.as_of_date, 365)) AS unmet_units_12m,
       (SELECT SUM(u.quantity_consumed * (p.selling_price - p.unit_cost)) / NULLIF(SUM(u.quantity_consumed), 0)
          FROM {{catalog}}.silver.usage_history u JOIN {{catalog}}.silver.product_master p USING (sku), {{catalog}}.gold.as_of a
         WHERE u.usage_date > DATE_SUB(a.as_of_date, 365)) AS avg_margin_per_unit
FROM {{catalog}}.gold.inventory_value_metrics;

-- ------------------------------------------------------------------------------------------- IoT (bonus)
CREATE OR REPLACE VIEW {{catalog}}.gold.device_telemetry_hourly
COMMENT 'Hourly device telemetry with anomaly scores (synthetic, illustrative).'
AS SELECT device_id, customer_id, DATE_TRUNC('HOUR', event_timestamp) AS hour,
          AVG(temperature_c) AS avg_temperature_c, AVG(vibration_mm_s) AS avg_vibration_mm_s,
          MAX(anomaly_score) AS max_anomaly_score, MAX(CAST(is_anomaly AS INT)) = 1 AS any_anomaly,
          SUM(CASE WHEN compressor_status = 'HIGH_LOAD' THEN 1 ELSE 0 END) AS high_load_readings
   FROM {{catalog}}.ml.device_telemetry_scored GROUP BY ALL;

CREATE OR REPLACE VIEW {{catalog}}.gold.device_health
COMMENT 'Latest device condition, potentially affected inventory and recommended inspection priority. A rising vibration score is an inspection signal, not proof of impending failure.'
AS
WITH last24 AS (
  SELECT device_id, MAX(anomaly_score) AS max_anomaly_score_24h, AVG(vibration_mm_s) AS avg_vibration_24h,
         AVG(temperature_c) AS avg_temperature_24h, SUM(CAST(is_anomaly AS INT)) AS anomalous_readings_24h
  FROM {{catalog}}.ml.device_telemetry_scored
  WHERE event_timestamp > (SELECT MAX(event_timestamp) FROM {{catalog}}.ml.device_telemetry_scored) - INTERVAL 24 HOURS
  GROUP BY device_id
), base AS (
  SELECT device_id, AVG(vibration_mm_s) AS baseline_vibration, AVG(temperature_c) AS baseline_temperature
  FROM {{catalog}}.ml.device_telemetry_scored
  WHERE event_timestamp < (SELECT MIN(event_timestamp) FROM {{catalog}}.ml.device_telemetry_scored) + INTERVAL 14 DAYS
  GROUP BY device_id
), inv AS (
  SELECT device_id, SUM(inventory_value) AS inventory_value_in_device, SUM(on_hand_qty) AS units_in_device,
         SUM(CASE WHEN critical_stock_flag THEN on_hand_qty ELSE 0 END) AS critical_units_in_device
  FROM {{catalog}}.gold.inventory_lots_current GROUP BY device_id
)
SELECT d.device_id, d.customer_id, c.customer_name, c.region, d.device_type, d.storage_type,
       l.max_anomaly_score_24h, l.anomalous_readings_24h, l.avg_vibration_24h, b.baseline_vibration,
       l.avg_temperature_24h, b.baseline_temperature,
       COALESCE(i.inventory_value_in_device, 0) AS inventory_value_in_device, COALESCE(i.units_in_device, 0) AS units_in_device,
       COALESCE(i.critical_units_in_device, 0) AS critical_units_in_device,
       CASE WHEN l.max_anomaly_score_24h >= 0.8 AND (COALESCE(i.inventory_value_in_device, 0) >= 50000 OR COALESCE(i.critical_units_in_device, 0) > 0) THEN 'HIGH'
            WHEN l.max_anomaly_score_24h >= 0.8 THEN 'MEDIUM'
            WHEN l.max_anomaly_score_24h >= 0.5 THEN 'WATCH'
            ELSE 'ROUTINE' END AS inspection_priority
FROM {{catalog}}.silver.rni_devices d
JOIN {{catalog}}.silver.customer_master c USING (customer_id)
JOIN last24 l USING (device_id)
LEFT JOIN base b USING (device_id)
LEFT JOIN inv i USING (device_id);

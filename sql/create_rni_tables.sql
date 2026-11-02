-- =====================================================================================================
-- RNI Intelligent Operations Command Center — Unity Catalog tables
-- Catalog placeholder {{catalog}} is substituted by scripts/load_rni_data.py (default: rni_demo).
-- ALL DATA IS SYNTHETIC. No PHI, no patient identities, no real customers/products.
-- bronze = raw synthetic source extracts (adapters), silver = typed/validated operational tables,
-- ml = forecasting + decision-engine outputs, gold = curated business views (sql/create_gold_views.sql).
-- Tables carry TBLPROPERTIES ('rni_demo.managed'='true'); the loader refuses to replace any table without it.
-- =====================================================================================================

CREATE SCHEMA IF NOT EXISTS {{catalog}}.bronze COMMENT 'RNI demo: raw synthetic source extracts (simulated RNI MySQL / SAP / ClearBlade feeds).';
CREATE SCHEMA IF NOT EXISTS {{catalog}}.silver COMMENT 'RNI demo: validated, typed operational tables (synthetic).';
CREATE SCHEMA IF NOT EXISTS {{catalog}}.ml     COMMENT 'RNI demo: demand forecasts, backtests, decision-engine outputs, IoT scores.';
CREATE SCHEMA IF NOT EXISTS {{catalog}}.gold   COMMENT 'RNI demo: curated business views shared by Dashboard, App and Genie.';
CREATE VOLUME IF NOT EXISTS {{catalog}}.bronze.landing COMMENT 'Landing zone for synthetic source extracts (Parquet).';

-- ----------------------------------------------------------------------------------------------- masters
CREATE OR REPLACE TABLE {{catalog}}.silver.customer_master (
  customer_id     STRING NOT NULL COMMENT 'Stable RNI customer location identifier (e.g. CUST-001).',
  customer_name   STRING NOT NULL COMMENT 'Fictional customer location name. "Desert Crest Medical Center" (CUST-001) is the executive demo scenario site.',
  location        STRING COMMENT 'City, state of the customer location (fictional site).',
  customer_type   STRING COMMENT 'Facility type, e.g. Hospital, Infusion Center, Critical Access Hospital, Specialty Clinic.',
  region          STRING COMMENT 'Sales/service region: West, Southwest, Midwest, Southeast, Northeast.',
  review_weekday  INT    COMMENT 'Day of week (0=Mon) the site performs its weekly RNI replenishment review.',
  onboarded_date  DATE   COMMENT 'Date the site joined the RNI program.',
  CONSTRAINT pk_customer_master PRIMARY KEY (customer_id)
) COMMENT 'RNI customer locations (synthetic).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.product_master (
  sku                 STRING NOT NULL COMMENT 'Stable product/SKU identifier (e.g. SKU-1001). SKU-1001 (Hyperimmune Globulin 1,500 IU) is the demo scenario product.',
  product_name        STRING NOT NULL COMMENT 'Fictional product name attached to a generic therapeutic category.',
  product_category    STRING COMMENT 'Therapeutic/product category, e.g. Immune Globulin, Antivenom & Antitoxin, Vaccines.',
  unit_cost           DOUBLE COMMENT 'Synthetic inventory value per unit (USD). Used for all inventory value metrics.',
  shelf_life_days     INT    COMMENT 'Shelf life from manufacture in days.',
  storage_type        STRING COMMENT 'REFRIGERATED (2-8C), FROZEN or ROOM_TEMP storage requirement.',
  critical_stock_flag BOOLEAN COMMENT 'TRUE for emergency/critical products whose stock is governed by mandatory minimums.',
  pack_size           INT    COMMENT 'Shipping pack multiple; replenishment quantities are rounded up to this.',
  unit_of_measure     STRING COMMENT 'Unit of measure (dose, vial, unit, syringe, kit).',
  selling_price       DOUBLE COMMENT 'Synthetic selling price per unit (USD).',
  manufacturer        STRING COMMENT 'Fictional manufacturer.',
  cold_chain_required BOOLEAN COMMENT 'TRUE if refrigerated or frozen — returns require qualified cold-chain shipping.',
  CONSTRAINT pk_product_master PRIMARY KEY (sku)
) COMMENT 'Pharmaceutical products stocked in RNI devices (synthetic, fictional names).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.rni_devices (
  device_id        STRING NOT NULL COMMENT 'Stable RNI device identifier (smart fridge/freezer/cabinet).',
  customer_id      STRING NOT NULL COMMENT 'Customer location where the device is installed.',
  device_type      STRING COMMENT 'RNI SmartFridge, RNI SmartFreezer or RNI SmartCabinet.',
  storage_type     STRING COMMENT 'Storage condition the device provides.',
  firmware_version STRING COMMENT 'Device firmware version (synthetic).',
  install_date     DATE   COMMENT 'Device installation date.',
  device_status    STRING COMMENT 'ACTIVE / INACTIVE.',
  CONSTRAINT pk_rni_devices PRIMARY KEY (device_id)
) COMMENT 'RNI inventory devices deployed at customer locations (synthetic).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.customer_product_assignments (
  customer_id           STRING NOT NULL COMMENT 'Customer location.',
  sku                   STRING NOT NULL COMMENT 'Product assigned to the location.',
  device_id             STRING NOT NULL COMMENT 'Device that stores this SKU at the location.',
  assignment_start_date DATE   COMMENT 'Start of the assignment.',
  scenario_id           STRING COMMENT 'Executive demo scenario this pair belongs to (SCN-01..SCN-06), else NULL.',
  CONSTRAINT pk_assignments PRIMARY KEY (customer_id, sku)
) COMMENT 'Which SKUs each RNI location stocks, and in which device (synthetic).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.par_levels (
  customer_id                  STRING NOT NULL COMMENT 'Customer location.',
  sku                          STRING NOT NULL COMMENT 'Product.',
  par_level                    INT    COMMENT 'PAR: contracted target stock level for the location/SKU (units).',
  mandatory_minimum            INT    COMMENT 'Approved mandatory minimum stock that must be held regardless of forecast (units).',
  replenishment_lead_time_days INT    COMMENT 'Days from shipment to receipt at the device.',
  review_period_days           INT    COMMENT 'Days between scheduled replenishment reviews.',
  stocking_policy_source       STRING COMMENT 'Source of the stocking policy (SIMULATED_CONTRACT).',
  effective_date               DATE   COMMENT 'Policy effective date.',
  CONSTRAINT pk_par_levels PRIMARY KEY (customer_id, sku)
) COMMENT 'PAR and mandatory minimum stocking policy per location/SKU (simulated business policy).' TBLPROPERTIES ('rni_demo.managed'='true');
ALTER TABLE {{catalog}}.silver.par_levels ADD CONSTRAINT chk_par_nonneg CHECK (par_level >= 0 AND mandatory_minimum >= 0);

CREATE OR REPLACE TABLE {{catalog}}.silver.dosing_rules (
  sku                      STRING NOT NULL COMMENT 'Product.',
  rule_version             STRING NOT NULL COMMENT 'Policy version (v1, v2...).',
  approved_stocking_policy STRING COMMENT 'Approved stocking policy: CRITICAL_MINIMUM_HOLD, PAR_REPLENISH, MIN_MAX_REVIEW, SEASONAL_PREBUILD_WITH_PAR_CAP.',
  review_required          BOOLEAN COMMENT 'TRUE if any change to stocking for this SKU requires human review.',
  effective_date           DATE   COMMENT 'Date this rule version became effective.',
  superseded_date          DATE   COMMENT 'Date this rule version was superseded (NULL = current).',
  policy_notes             STRING COMMENT 'Notes. These are simulated STOCKING-POLICY metadata, never patient dosing instructions.',
  CONSTRAINT pk_dosing_rules PRIMARY KEY (sku, rule_version)
) COMMENT 'Simulated stocking-policy metadata per SKU (named dosing_rules for RNI alignment; contains NO patient dosing).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.lot_master (
  lot_id           STRING NOT NULL COMMENT 'Stable manufacturing lot identifier.',
  sku              STRING NOT NULL COMMENT 'Product the lot belongs to.',
  manufacture_date DATE COMMENT 'Lot manufacture date.',
  release_date     DATE COMMENT 'Date the lot was released for distribution.',
  expiry_date      DATE COMMENT 'Lot expiration date.',
  is_scenario_lot  BOOLEAN COMMENT 'TRUE for lots created to stage an executive scenario (e.g. the short-dated lot in SCN-02).',
  CONSTRAINT pk_lot_master PRIMARY KEY (lot_id)
) COMMENT 'Manufacturing lots and expiration dates (synthetic).' TBLPROPERTIES ('rni_demo.managed'='true');

-- ----------------------------------------------------------------------------------------------- transactions
CREATE OR REPLACE TABLE {{catalog}}.silver.usage_history (
  customer_id       STRING NOT NULL COMMENT 'Customer location.',
  sku               STRING NOT NULL COMMENT 'Product.',
  device_id         STRING NOT NULL COMMENT 'Device the product was dispensed from.',
  usage_date        DATE   NOT NULL COMMENT 'Date of consumption.',
  quantity_consumed INT    NOT NULL COMMENT 'Units dispensed for use (utilization). Shipments/returns are NOT consumption.'
) COMMENT 'Daily product utilization (consumption) at RNI devices. Distinct from product movement.' TBLPROPERTIES ('rni_demo.managed'='true');
ALTER TABLE {{catalog}}.silver.usage_history ADD CONSTRAINT chk_usage_pos CHECK (quantity_consumed > 0);

CREATE OR REPLACE TABLE {{catalog}}.silver.stockout_events (
  customer_id STRING NOT NULL COMMENT 'Customer location.',
  sku         STRING NOT NULL COMMENT 'Product.',
  event_date  DATE   NOT NULL COMMENT 'Date demand could not be met from device stock.',
  unmet_qty   INT    COMMENT 'Units of demand not met from on-hand stock.'
) COMMENT 'Days on which device stock was insufficient for demand (synthetic).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.shipment_orders (
  order_id              STRING NOT NULL COMMENT 'Replenishment order (one per customer per review day).',
  order_line_id         STRING NOT NULL COMMENT 'Order line identifier (one SKU per line).',
  customer_id           STRING NOT NULL COMMENT 'Customer location.',
  sku                   STRING NOT NULL COMMENT 'Product.',
  request_date          DATE   NOT NULL COMMENT 'Date the replenishment was requested.',
  requested_qty         INT    NOT NULL COMMENT 'Quantity requested by the site/planner (simulated manual Excel decision).',
  approved_qty          INT    COMMENT 'Quantity approved by FFF review (NULL while PENDING_REVIEW).',
  shipped_qty           INT    COMMENT 'Quantity actually shipped from SAP.',
  shipment_date         DATE   COMMENT 'SAP ship date.',
  delivered_date        DATE   COMMENT 'Date received into the RNI device.',
  order_status          STRING NOT NULL COMMENT 'PENDING_REVIEW, APPROVED, IN_TRANSIT, DELIVERED, PARTIALLY_DELIVERED, REJECTED, CANCELLED.',
  decision_source       STRING COMMENT 'How the request quantity was decided (MANUAL_EXCEL_SIMULATED).',
  request_channel       STRING COMMENT 'Channel the request arrived through.',
  synthetic_excess_flag BOOLEAN COMMENT 'GROUND TRUTH (synthetic only): request was intentionally generated as an excessive allocation.',
  scenario_id           STRING COMMENT 'Executive demo scenario for the open request, else NULL.',
  sap_delivery_id       STRING COMMENT 'Synthetic SAP outbound delivery number.',
  CONSTRAINT pk_shipment_orders PRIMARY KEY (order_line_id)
) COMMENT 'Shipment requests and SAP shipments at order-line grain (synthetic).' TBLPROPERTIES ('rni_demo.managed'='true');
ALTER TABLE {{catalog}}.silver.shipment_orders ADD CONSTRAINT chk_order_status CHECK (order_status IN ('PENDING_REVIEW','APPROVED','IN_TRANSIT','DELIVERED','PARTIALLY_DELIVERED','REJECTED','CANCELLED'));
ALTER TABLE {{catalog}}.silver.shipment_orders ADD CONSTRAINT chk_order_qty CHECK (requested_qty > 0 AND (shipped_qty IS NULL OR shipped_qty >= 0));

CREATE OR REPLACE TABLE {{catalog}}.silver.shipment_lot_allocations (
  order_line_id STRING NOT NULL COMMENT 'Order line that shipped the lot.',
  lot_id        STRING NOT NULL COMMENT 'Lot shipped.',
  allocated_qty INT    COMMENT 'Units of the lot shipped on the line.',
  expiry_date   DATE   COMMENT 'Expiry of the shipped lot.'
) COMMENT 'Lot allocation of each shipped order line (synthetic).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.return_orders (
  return_id              STRING NOT NULL COMMENT 'Return transaction identifier.',
  customer_id            STRING NOT NULL COMMENT 'Customer location returning stock.',
  sku                    STRING NOT NULL COMMENT 'Product returned.',
  device_id              STRING COMMENT 'Device the stock was removed from.',
  lot_id                 STRING COMMENT 'Lot returned.',
  returned_qty           INT    NOT NULL COMMENT 'Units returned (never exceeds the lot quantity on hand).',
  return_date            DATE   NOT NULL COMMENT 'Return date.',
  return_reason          STRING COMMENT 'EXCESS_STOCK, SHORT_DATED, STOCK_ROTATION.',
  return_shipping_cost   DOUBLE COMMENT 'Synthetic return logistics cost incl. qualified cold-chain packaging (USD).',
  return_processing_cost DOUBLE COMMENT 'Synthetic receiving/QA/requalification cost (USD).',
  returned_value         DOUBLE COMMENT 'Inventory value of the returned units = returned_qty x unit_cost (USD). Not a loss by itself.',
  cold_chain_shipment    BOOLEAN COMMENT 'TRUE if the return required cold-chain shipping.',
  lot_expiry_date        DATE   COMMENT 'Expiry date of the returned lot.',
  source_order_line_id   STRING COMMENT 'SYNTHETIC link to the originating order line when exactly one candidate exists.',
  order_link_type        STRING COMMENT 'SYNTHETIC_SINGLE_CANDIDATE, AMBIGUOUS (multiple candidate orders), UNLINKED_OPENING_STOCK. RNI has no direct order-to-return traceability today.',
  scenario_id            STRING COMMENT 'Executive demo scenario, else NULL.',
  CONSTRAINT pk_return_orders PRIMARY KEY (return_id)
) COMMENT 'Returns of RNI stock to FFF, with cold-chain logistics cost (synthetic).' TBLPROPERTIES ('rni_demo.managed'='true');
ALTER TABLE {{catalog}}.silver.return_orders ADD CONSTRAINT chk_return_qty CHECK (returned_qty > 0);

CREATE OR REPLACE TABLE {{catalog}}.silver.return_order_links (
  return_id         STRING NOT NULL COMMENT 'Return.',
  order_line_id     STRING NOT NULL COMMENT 'Candidate originating order line (delivered the same lot to the same site).',
  link_type         STRING COMMENT 'SYNTHETIC_SINGLE_CANDIDATE or AMBIGUOUS.',
  link_confidence   DOUBLE COMMENT '1 / number of candidate order lines.',
  is_synthetic_link BOOLEAN COMMENT 'Always TRUE: links are synthetic for future reconciliation demos.'
) COMMENT 'Synthetic return-to-order candidate links (RNI currently lacks direct traceability).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.inventory_events (
  event_id          STRING NOT NULL COMMENT 'Ledger event identifier (chronological).',
  event_seq         BIGINT NOT NULL COMMENT 'Chronological sequence number.',
  event_date        DATE   NOT NULL COMMENT 'Event date.',
  customer_id       STRING NOT NULL COMMENT 'Customer location.',
  device_id         STRING NOT NULL COMMENT 'Device.',
  sku               STRING NOT NULL COMMENT 'Product.',
  lot_id            STRING NOT NULL COMMENT 'Lot.',
  event_type        STRING NOT NULL COMMENT 'OPENING_BALANCE, RECEIPT, CONSUMPTION, RETURN, EXPIRY_DISPOSAL.',
  quantity_delta    INT    NOT NULL COMMENT 'Signed quantity change (+ receipts/opening, - consumption/returns/disposal).',
  reference_type    STRING COMMENT 'ORDER_LINE, RETURN, USAGE, EXPIRY, OPENING.',
  reference_id      STRING COMMENT 'Identifier of the referenced transaction.',
  lot_balance_after INT    COMMENT 'Running on-hand balance of the lot at the site after the event.',
  CONSTRAINT pk_inventory_events PRIMARY KEY (event_id)
) COMMENT 'Lot-level inventory event ledger: opening + receipts - consumption - returns - disposal = closing.' TBLPROPERTIES ('rni_demo.managed'='true');
ALTER TABLE {{catalog}}.silver.inventory_events ADD CONSTRAINT chk_event_type CHECK (event_type IN ('OPENING_BALANCE','RECEIPT','CONSUMPTION','RETURN','EXPIRY_DISPOSAL'));
ALTER TABLE {{catalog}}.silver.inventory_events ADD CONSTRAINT chk_balance_nonneg CHECK (lot_balance_after >= 0);

CREATE OR REPLACE TABLE {{catalog}}.silver.inventory_positions (
  customer_id   STRING NOT NULL COMMENT 'Customer location.',
  device_id     STRING NOT NULL COMMENT 'Device.',
  sku           STRING NOT NULL COMMENT 'Product.',
  lot_id        STRING NOT NULL COMMENT 'Lot.',
  on_hand_qty   INT    NOT NULL COMMENT 'Units on hand at end of snapshot_date.',
  expiry_date   DATE   COMMENT 'Lot expiry date.',
  snapshot_date DATE   NOT NULL COMMENT 'Snapshot date (month-ends plus the current demo snapshot).',
  is_current    BOOLEAN COMMENT 'TRUE for the current (latest) snapshot.'
) COMMENT 'Inventory at customer/device/SKU/lot level, derived from the event ledger.' TBLPROPERTIES ('rni_demo.managed'='true');
ALTER TABLE {{catalog}}.silver.inventory_positions ADD CONSTRAINT chk_onhand_nonneg CHECK (on_hand_qty >= 0);

CREATE OR REPLACE TABLE {{catalog}}.silver.scenario_registry (
  scenario_id            STRING NOT NULL COMMENT 'SCN-01..SCN-06.',
  scenario_name          STRING COMMENT 'Scenario name.',
  scenario_type          STRING COMMENT 'EXCESSIVE_SHIPMENT, EXPIRATION_RISK, STOCKOUT_RISK, INTERMITTENT_CRITICAL_DEMAND, HIGH_RETURNS_COST, AMBIGUOUS_RETURN.',
  customer_id            STRING COMMENT 'Customer location.',
  sku                    STRING COMMENT 'Product.',
  narrative              STRING COMMENT 'Executive narrative.',
  optional               BOOLEAN COMMENT 'Optional scenario.',
  requested_qty          INT    COMMENT 'Open request quantity staged for the demo.',
  expected_risk_category STRING COMMENT 'Risk category the decision engine is expected to assign.',
  CONSTRAINT pk_scenario_registry PRIMARY KEY (scenario_id)
) COMMENT 'Executive demo scenarios from config/demo_scenarios.yaml.' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.silver.device_telemetry (
  device_id         STRING NOT NULL COMMENT 'RNI device.',
  customer_id       STRING NOT NULL COMMENT 'Customer location.',
  event_timestamp   TIMESTAMP NOT NULL COMMENT 'Reading timestamp (15-minute interval).',
  temperature_c     DOUBLE COMMENT 'Internal temperature (C).',
  vibration_mm_s    DOUBLE COMMENT 'Compressor vibration RMS velocity (mm/s).',
  compressor_status STRING COMMENT 'RUNNING, IDLE, DEFROST, HIGH_LOAD.',
  door_open_events  INT    COMMENT 'Door openings in the interval.'
) COMMENT 'Synthetic RNI device telemetry (simulated ClearBlade/PubSub feed) — illustrative only.' TBLPROPERTIES ('rni_demo.managed'='true');

-- ----------------------------------------------------------------------------------------------- ml outputs
CREATE OR REPLACE TABLE {{catalog}}.ml.demand_forecasts (
  customer_id            STRING NOT NULL COMMENT 'Customer location.',
  sku                    STRING NOT NULL COMMENT 'Product.',
  forecast_date          DATE   NOT NULL COMMENT 'As-of date of the forecast (the demo snapshot).',
  forecast_horizon       INT    NOT NULL COMMENT 'Forecast horizon in days (30, 60, 90).',
  horizon_label          STRING COMMENT 'Human-readable horizon.',
  predicted_demand       DOUBLE COMMENT 'Forecast total units consumed over the horizon.',
  lower_bound            DOUBLE COMMENT 'Lower bound of the 80% prediction interval.',
  upper_bound            DOUBLE COMMENT 'Upper bound of the 80% prediction interval.',
  interval_level         DOUBLE COMMENT 'Nominal interval level (0.8).',
  interval_method        STRING COMMENT 'Empirical bootstrap with split-conformal calibration from the backtest.',
  model_name             STRING COMMENT 'Model selected for this series demand class by backtest MAE.',
  demand_class           STRING COMMENT 'SMOOTH, ERRATIC, INTERMITTENT, LUMPY, NO_RECENT_DEMAND (Syntetos-Boylan).',
  seasonal_flag          BOOLEAN COMMENT 'Year-over-year seasonality detected.',
  model_version          STRING COMMENT 'Registered model version (Unity Catalog) used.',
  training_cutoff_date   DATE   COMMENT 'Last date of observations the model was allowed to use.',
  training_obs_max_date  DATE   COMMENT 'Latest usage observation actually used (must be <= training_cutoff_date).',
  max_weekly_demand_104w DOUBLE COMMENT 'Largest single-week demand in the 104-week training window.',
  nonzero_weeks_104w     INT    COMMENT 'Weeks with any demand in the training window.',
  mlflow_run_id          STRING COMMENT 'MLflow run that produced the forecast.'
) COMMENT 'Demand forecasts produced by executing the forecasting pipeline (not fabricated).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.ml.demand_forecast_weekly (
  customer_id             STRING, sku STRING, forecast_date DATE,
  week_start              DATE   COMMENT 'Start of the forecast week.',
  predicted_weekly_demand DOUBLE COMMENT 'Point forecast for the week.',
  lower_bound             DOUBLE COMMENT 'Lower bound (80%, uncalibrated weekly bootstrap).',
  upper_bound             DOUBLE COMMENT 'Upper bound (80%, uncalibrated weekly bootstrap).',
  model_name              STRING, model_version STRING, mlflow_run_id STRING
) COMMENT 'Weekly forecast path for charting next to weekly history.' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.ml.forecast_backtest_metrics (
  demand_class STRING, model_name STRING, horizon_days INT, n_series DOUBLE,
  mae DOUBLE COMMENT 'Mean absolute error of horizon totals.',
  wape DOUBLE COMMENT 'Weighted absolute percentage error.',
  bias DOUBLE COMMENT 'Sum(forecast-actual)/sum(actual); negative = under-forecast.',
  under_forecast_share DOUBLE COMMENT 'Stockout-sensitive: share of actual demand above the forecast.',
  exceed_upper_rate DOUBLE COMMENT 'Stockout-sensitive: share of series whose actual exceeded the upper bound.',
  interval_coverage DOUBLE COMMENT 'Share of actuals inside the raw bootstrap interval.',
  selected BOOLEAN COMMENT 'Model selected for the demand class.',
  mlflow_run_id STRING
) COMMENT 'Rolling-origin backtest (3 origins) of every candidate model.' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.ml.replenishment_recommendations (
  recommendation_id             STRING NOT NULL COMMENT 'Recommendation identifier.',
  recommendation_type           STRING COMMENT 'SHIPMENT_REQUEST (pending request) or CYCLE_REVIEW (proactive review of every pair).',
  order_line_id                 STRING COMMENT 'Pending order line evaluated (SHIPMENT_REQUEST).',
  scenario_id                   STRING COMMENT 'Executive scenario, else NULL.',
  customer_id                   STRING NOT NULL, sku STRING NOT NULL,
  requested_qty                 INT    COMMENT 'Requested quantity (NULL for cycle reviews).',
  on_hand_qty                   INT    COMMENT 'On hand at snapshot.',
  pending_inbound_qty           INT    COMMENT 'Units in transit.',
  par_level                     INT, mandatory_minimum INT, lead_time_days INT,
  forecast_qty                  DOUBLE COMMENT '30-day forecast demand.',
  forecast_upper                DOUBLE COMMENT '30-day forecast upper bound.',
  forecast_lower                DOUBLE COMMENT '30-day forecast lower bound.',
  recommended_qty               INT    COMMENT 'Decision-engine recommended quantity (deterministic; never LLM-generated).',
  par_only_baseline_qty         INT    COMMENT 'Simplified PAR - on hand baseline, for comparison only.',
  target_inventory              INT    COMMENT 'Policy-constrained target inventory.',
  effective_available_qty       DOUBLE COMMENT 'Usable on hand + in transit.',
  projected_expiring_unused_qty DOUBLE COMMENT 'Near-expiry units projected to expire unused.',
  near_expiry_qty               INT    COMMENT 'Units expiring within 90 days.',
  excess_qty                    INT    COMMENT 'Requested minus recommended (>= 0).',
  potential_exposure_value      DOUBLE COMMENT 'excess_qty x unit_cost — potential inventory exposure, NOT realized savings.',
  request_cover_days            DOUBLE COMMENT 'Days of forecast demand the request would leave on hand.',
  risk_category                 STRING COMMENT 'EXCESSIVE_REQUEST, STOCKOUT_RISK, EXPIRY_RISK, CRITICAL_POLICY_HOLD, WITHIN_POLICY, MISSING_DATA.',
  risk_factors                  STRING COMMENT 'JSON array of all risk factors.',
  policy_constraints            STRING COMMENT 'JSON array of applied policy constraints.',
  human_review_required         BOOLEAN COMMENT 'TRUE if a human reviewer must decide.',
  review_reason                 STRING COMMENT 'Why review is required.',
  explanation                   STRING COMMENT 'JSON array of explanation steps.',
  engine_input                  STRING COMMENT 'JSON of the exact engine inputs (for replay/audit).',
  model_version                 STRING, engine_version STRING, rule_version STRING,
  snapshot_date                 DATE, created_at TIMESTAMP
) COMMENT 'Replenishment recommendations produced by executing the decision engine (not fabricated).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.ml.device_telemetry_scored (
  device_id STRING, customer_id STRING, event_timestamp TIMESTAMP, temperature_c DOUBLE, vibration_mm_s DOUBLE,
  compressor_status STRING,
  z_vibration   DOUBLE COMMENT 'Vibration z-score vs the device''s own first-14-day baseline (4h rolling mean).',
  z_temperature DOUBLE COMMENT 'Temperature z-score vs baseline.',
  anomaly_score DOUBLE COMMENT '0-1 logistic transform of the max z-score (>=0.8 = anomalous). Illustrative, not a failure prediction.',
  is_anomaly    BOOLEAN COMMENT 'anomaly_score >= 0.8 sustained for >= 1 hour.'
) COMMENT 'IoT telemetry scored by the rolling-baseline anomaly detector (src/iot/anomaly.py).' TBLPROPERTIES ('rni_demo.managed'='true');

CREATE OR REPLACE TABLE {{catalog}}.ml.simulation_ground_truth (
  customer_id STRING, sku STRING, demand_profile STRING COMMENT 'Generating process (REGULAR/SEASONAL/INTERMITTENT/EMERGENCY).',
  mean_daily_demand DOUBLE, p_excess DOUBLE, return_propensity DOUBLE, ordering_bias DOUBLE
) COMMENT 'Synthetic generator ground truth for evaluation only. Not exposed to Genie, App or Dashboard.' TBLPROPERTIES ('rni_demo.managed'='true');

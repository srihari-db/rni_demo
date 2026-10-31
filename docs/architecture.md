# Architecture — RNI Intelligent Operations Command Center

```
 Existing RNI sources (SIMULATED)                       Databricks (workspace e2-demo-field-eng, AWS us-west-2)
 ┌───────────────────────────────┐   synthetic    ┌──────────────────────────────────────────────────────────────┐
 │ Cloud SQL MySQL  (inventory,  │   source       │ Unity Catalog  rni_demo                                       │
 │   PAR, usage)                 │   adapters     │  bronze ─► silver ─► ml ─────────► gold (shared definitions)  │
 │ Cloud SQL PostgreSQL (telem.) │ ─────────────► │   raw      typed     forecasts       views + KPI table +       │
 │ SAP (orders, shipments,       │ (src/data/     │   extracts CHECKs    recommendations metric view              │
 │      returns)                 │  adapters.py)  │                      IoT scores                               │
 │ ClearBlade IoT / Pub/Sub      │                │        ▲ Lakeflow Job (serverless, on demand)                 │
 └───────────────────────────────┘                │  generate → load → forecast(MLflow) → decision engine → gold   │
                                                  │                                     → pytest data tests        │
                                                  ├──────────────────────────────────────────────────────────────┤
                                                  │ AI/BI Dashboard  "RNI Executive Inventory Intelligence"       │
                                                  │ Genie agent      "RNI Inventory Intelligence Agent"           │
                                                  │ Databricks App   "rni-command-center" (Streamlit)             │
                                                  │   ├─ SQL warehouse (gold, read-only, app service principal)   │
                                                  │   ├─ Genie Conversation API                                   │
                                                  │   ├─ Foundation Model endpoint (narrative only)               │
                                                  │   └─ Lakebase Postgres Autoscaling (cases, reviews, audit)    │
                                                  └──────────────────────────────────────────────────────────────┘
```

## Separation of concerns

| Layer | Code | Notes |
|---|---|---|
| Data generation | `src/data/simulator.py`, `catalog.py`, `scripts/generate_rni_data.py` | separate from app code; fails fast on any quality check |
| Data quality | `src/data/quality.py`, `tests/test_data_integrity.py` | same checks in generator, local tests and live UC tests |
| Data access | `src/data/warehouse.py` | declared query specs over approved Gold views; read-only; parameterized |
| Forecasting | `src/forecasting/` | numpy/pandas; backtest → select → conformal intervals; MLflow + UC registry in the job script |
| Optimization | `src/optimization/engine.py`, `batch.py` | deterministic stdlib engine; same code in job, App and tests |
| Genie | `src/genie/` | space config (definitions, verified SQL, benchmarks), Conversation API client, labeled fallback |
| Agents | `src/agents/` | bounded workflow: fixed fact tools → engine rerun → LLM narrative only → case |
| Value | `src/value/simulator.py` | released inventory vs cost avoidance vs cash, kept separate |
| Persistence | `src/lakebase/store.py` | Lakebase (OAuth, token refresh) with labeled demo-only SQLite fallback |
| Presentation | `app/`, `scripts/setup_dashboard.py` | Streamlit App + AI/BI dashboard; both read the same Gold objects |

## Guardrails

- **Quantities.** Only the deterministic engine computes them. The LLM gets a fact sheet and returns narrative JSON;
  the case stores the engine's quantity and the human-approved quantity, nothing else.
- **Critical products.** Forecasts can't push stock below the mandatory minimum. Targets are raised to the largest
  observed single-week demand, and review is mandatory.
- **No SAP writes.** There is no SAP client, and approving a case records a human decision only. A test scans the
  code for external-write libraries.
- **SQL.** The App runs only declared SELECTs on approved Gold views. Genie runs on Gold views only, and its answers
  are labeled; a curated fallback is explicitly labeled as not a Genie response.
- **Ownership guard.** Loaders refuse to replace tables that lack `TBLPROPERTIES ('rni_demo.managed'='true')`.
- **Least privilege.** The App service principal has `USE CATALOG`, `USE SCHEMA` and `SELECT` on `rni_demo.gold`
  only, plus resource-scoped warehouse / Genie / endpoint / Lakebase permissions.

## IoT future integration (bonus)

The demo uses synthetic 15-minute telemetry scored by a rolling-baseline detector. Production paths:

1. ClearBlade → Pub/Sub → **Zerobus Ingest** (gRPC writes straight into a UC Delta table, no message bus to run).
   Alternative: keep Pub/Sub and use Structured Streaming with the Pub/Sub source.
2. The same `silver.device_telemetry` schema, so Gold consumers don't change.
3. Join with lot-level inventory to rank inspections by value at risk and critical stock, and raise planner cases
   through the existing workflow.

A rising vibration score is an *inspection signal*; this demo doesn't claim it predicts failure.

## Real-source adapters (future)

`src/data/adapters.py` defines the `RniSource` interface. Planned adapters:

- Lakehouse Federation or Lakeflow Connect to Cloud SQL (MySQL / PostgreSQL)
- SAP extracts or a connector for orders, deliveries and returns
- Telemetry streaming

The demo needs no live GCP or SAP access.

# Deployment Guide

## Environment used for this build

| Item | Value |
|---|---|
| Workspace | `https://e2-demo-field-eng.cloud.databricks.com` (AWS us-west-2). The brief targets Azure Databricks; the same APIs and bundle work there unchanged. |
| CLI profile | `DEFAULT` |
| Catalog | `rni_demo` (configurable through the bundle variable `catalog`) |
| SQL warehouse | `6674ed0664e1e8a3` (existing shared serverless warehouse; passed as `--var warehouse_id`) |
| LLM endpoint | `databricks-claude-sonnet-4-5` (bundle variable `llm_endpoint`; used for narrative only) |
| Lakebase | Autoscaling project `rni-ops-cases` (0.5–1 CU, suspends after 10 minutes idle) |

## Required permissions

- **Deployer:**
  - `USE CATALOG` + `CREATE SCHEMA` on the catalog (or catalog ownership)
  - `CAN_USE` on the warehouse
  - create Apps, Jobs, Genie spaces, dashboards and Lakebase projects
  - `CAN_QUERY` on the LLM endpoint
- **App service principal** (created automatically with the app):
  - `USE CATALOG`, `USE SCHEMA` and `SELECT` on `<catalog>.gold` only (`scripts/grant_app_access.py`)
  - warehouse `CAN_USE`, Genie `CAN_RUN`, endpoint `CAN_QUERY` and Lakebase `CAN_CONNECT_AND_CREATE`, all through
    app resources

## Steps (dev target)

```bash
export DATABRICKS_CONFIG_PROFILE=DEFAULT
WH=<warehouse-id>

# 1. Data pipeline: job + Lakebase project (first deploy without the app until the Genie space exists)
databricks bundle deploy --var warehouse_id=$WH
databricks bundle run rni_data_pipeline --var warehouse_id=$WH
#    generate -> load UC -> forecast (MLflow, UC model) -> decision engine -> gold -> pytest (live UC checks)

# 2. Genie space (verifies SQL, creates/updates the space, runs benchmarks)
python scripts/setup_genie.py --warehouse-id $WH
GENIE=$(cat config/genie_space_id.txt)

# 3. AI/BI dashboard (tests every dataset query, creates/updates and publishes)
python scripts/setup_dashboard.py --warehouse-id $WH

# 4. App (resources: warehouse, LLM endpoint, Genie space, Lakebase) + least-privilege UC grants
databricks bundle deploy --var warehouse_id=$WH --var genie_space_id=$GENIE
python scripts/grant_app_access.py --warehouse-id $WH
databricks bundle run rni_command_center --var warehouse_id=$WH --var genie_space_id=$GENIE
```

**Demo target:** use `-t demo`. Resources are prefixed `[demo]` and are created under the deployer, in production
mode. It never points at production RNI resources.

**Rebuild the data at any time:** run `databricks bundle run rni_data_pipeline`. It's deterministic. Every table is
replaced only if it carries `rni_demo.managed=true`.

## Cost controls

- The job is serverless and on demand, with no schedule.
- The App uses Medium compute. Stop it with `databricks apps stop rni-command-center` when it isn't needed.
- Lakebase scales to zero after 10 minutes idle.
- Forecasts are precomputed, so no model training runs during the demo.

## Local development

PyPI was blocked on the build laptop, so all heavy execution runs in the Databricks job, which also runs the full
pytest suite. Locally, the engine and simulator run with plain `numpy`/`pandas`. For local app testing, install
`requirements.txt` and set:

- `DATABRICKS_WAREHOUSE_ID`
- `RNI_CATALOG`
- optionally `GENIE_SPACE_ID`, `SERVING_ENDPOINT_NAME` and `PG*`

Then run `streamlit run app/app.py`. With no `PG*` variables set, the app uses the labeled demo-only SQLite store.

## Teardown

```bash
databricks bundle destroy                      # job, app, Lakebase project
# Genie space and dashboard: delete in the UI (ids in config/*.txt)
# Data: DROP SCHEMA rni_demo.bronze/silver/ml/gold CASCADE (only if no longer needed)
```

# RNI Intelligent Operations Command Center — FFF Enterprises (executive demo)

Databricks demonstration for FFF Enterprises' **Right Now Inventory (RNI)** business. It covers:
- inventory risk
- demand forecasting
- detection of excessive shipment requests
- explainable, policy-constrained replenishment recommendations
- Genie natural-language analytics
- an AI-assisted human-review workflow
- an illustrative business-value simulator
- a bonus IoT extension

> **All data is synthetic** (fictional customers/products, no PHI). Recommendations are decision support, not
> clinical guidance. Nothing in this project creates or modifies SAP shipments or returns.

## Live resources (e2-demo-field-eng)

| Resource | Location |
|---|---|
| Databricks App | https://rni-command-center-1444828305810485.aws.databricksapps.com |
| AI/BI Dashboard | `/dashboardsv3/01f1d4e87ddf1efc9a8cb2250a916d0a/published` — *RNI Executive Inventory Intelligence* |
| Genie space | `01f1d4e83ebe1ea089da3d55bd01592f` — *RNI Inventory Intelligence Agent* |
| Data pipeline job | `rni-command-center-data-pipeline` (job id 282948484026879) |
| Unity Catalog | `rni_demo.{bronze,silver,ml,gold}` + volume `rni_demo.bronze.landing` |
| Model | `rni_demo.ml.rni_demand_forecaster` (MLflow experiment `rni_demo_demand_forecasting`) |
| Lakebase | Autoscaling project `rni-ops-cases` (schema `rni_ops`) |

## Repository layout

```
app/                Streamlit Databricks App (app.py, ui.py, services.py, pages/*)
src/data/           simulator, master catalog, quality checks, source adapters, Gold repository
src/forecasting/    models + backtest/selection/interval pipeline
src/optimization/   deterministic decision engine + batch runner
src/genie/          Genie space definition, Conversation API client, labeled curated fallback
src/agents/         case model/status workflow + bounded AI investigation workflow
src/value/          business value simulator
src/lakebase/       Lakebase case store (+ demo-only SQLite fallback)
src/iot/            telemetry anomaly detector
scripts/            generate_rni_data, load_rni_data, run_forecasting, run_recommendations, build_gold,
                    run_tests, setup_genie, setup_dashboard, grant_app_access
sql/                create_rni_tables.sql, create_gold_views.sql
config/             demo_scenarios.yaml (simulation + executive scenarios), business_rules.yaml
dashboards/         generated AI/BI dashboard definition (.lvdash.json)
resources/          bundle resources: job, app, Lakebase project
tests/              data integrity, engine, forecasting, value/IoT, workflow/consistency, app smoke
docs/               data dictionary, architecture, deployment, demo script, model + Genie validation
databricks.yml      Declarative Automation Bundle (targets: dev, demo)
app.yaml            App runtime config (resources via valueFrom)
```

See `docs/deployment_guide.md` to deploy, `docs/demo_script.md` for the 25-minute walkthrough, and
`docs/synthetic_data_dictionary.md` for the data, row counts and validation results.

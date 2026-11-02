# 25-Minute Executive Demo Script — RNI Intelligent Operations Command Center

**Audience:** FFF Enterprises CIO, EVPs, VPs and technology leadership (RNI).

**Open these tabs before you start:**

1. AI/BI dashboard: *RNI Executive Inventory Intelligence*
2. App: <https://rni-command-center-1444828305810485.aws.databricksapps.com>
3. (Backup) the Genie space in the workspace UI

**Warm up 5 minutes before:** open the dashboard and every App page once, so the warehouse and Lakebase are awake.

**Ground rule to say up front:** *"Everything you'll see runs on synthetic data shaped like RNI's operations. No live
RNI, SAP or GCP systems are touched, and nothing we do today creates a shipment or a return."*

---

## 0–4 min · Executive dashboard

**Show:** the six KPI tiles, exposure by region and by category, consumption vs shipments, return trends, the top 10
locations, the expiration horizons, and the review table.

**Say:**
- "This is about $3.4M of product deployed in RNI devices across 15 sites."
- "About $1.4M is *potential* excess exposure: stock above PAR plus what pending requests would add beyond need.
  That's potential exposure, not savings."
- "The navy line is product *shipped* to sites; the teal line is product actually *used*. The gap is inventory
  building up, and it shows up later as returns. That's $4.8M returned in the last 12 months, and roughly $128K of
  cold-chain logistics on returns caused by over-allocation."

**Expected behavior:** the filters (region, customer, product, dates) change every tile consistently. The risk buckets
are mutually exclusive, so nothing is double-counted.

## 4–9 min · ML forecasting

**Do:** App → *Inventory Command Center*. Point at the red alert (Desert Crest · Hyperimmune Globulin). Click **Open in Intelligent
Shipment Advisor**.

**Say:**
- "Desert Crest Medical Center asked for 500 doses. It used one dose in the last four months."
- "The forecast was built by an MLflow-tracked pipeline that compared six models, including simple baselines, on
  rolling backtests. For sparse demand like this it picked an intermittent-demand method (TSB) on evaluated
  accuracy, not because it's the fanciest."
- "For emergency products, a forecast like this isn't safe to stock on by itself, and the system knows that."

**Expected behavior:** the weekly history bars, the forecast line and the 80% band are visible. The 30-day forecast
is about 0.7 doses.

## 9–15 min · Intelligent Shipment Advisor (centerpiece)

**Show:** the KPI row (Requested 500 · On hand 25 · PAR 60 · Minimum 40 · Used 1 · Forecast ≈ 0.7 · Recommended 15)
and the four-bar comparison (Original request · PAR-only baseline 35 · Policy-constrained recommendation 15 ·
Human-approved decision pending).

**Say:**
- "A simple PAR top-up would say 35. The engine applies the full policy: forecast demand over the 10-day coverage
  window, the mandatory minimum of 40, expiry, stock in transit and pack size of 5. That gives **15**."
- "Shipping 500 would create about **$436K of potential exposure**. That's why it's flagged, and a human must review
  it."
- "The quantity comes from a deterministic, testable engine. No AI model picks the number."

**Do — what-if controls:**
1. Set *Mandatory minimum* to 60. The recommendation becomes 35: policy drives the target.
2. Set *Requested* to 15. The *excessive* flag disappears, but the request is still routed to review as
   **Critical policy hold**: the site holds 25, below its mandatory minimum of 40, and this hyperimmune globulin is a critical
   product, so policy keeps a human in the loop.
3. Click **Reset**.

**Optional:** switch the product to *Crotivane Antivenom* at Mesa Verde (SCN-04). The forecast is near zero, but the
minimum of 8 holds and review is mandatory.

## 15–19 min · Ask Genie

**Do:** App → *Ask RNI AI*. Click three prevalidated questions:
1. "Which customers have the highest excess inventory exposure?"
2. "Why was Desert Crest's shipment request flagged?"
3. "How much was returned during the last 12 months?"

**Say:** "Genie answers in plain English on the same governed Gold tables the dashboard uses: same definitions, same
numbers. You can open the SQL it ran."

**Expected behavior:** each answer carries the green **Live Genie response** badge and shows a table, a chart and the
SQL. Answers take about 15–20 seconds.

**Fallback:** if Genie is slow, the App switches to fixed, verified queries badged **Curated SQL fallback — not a Genie
response**. Say so explicitly. The Genie space can also be opened directly in the workspace.

## 19–23 min · AI-assisted workflow

**Do:** in the Advisor, click **Create investigation case**. On *AI Operations Cases* the case appears with:
- an AI-generated summary (badge shows the model endpoint)
- the risk explanation
- missing information
- the proposed next action
- the evidence table

Then choose **Needs more information**, add a comment and submit. Reopen the case and **Approve** with a
human-approved quantity of 15.

**Say:** "The assistant gathers the facts through fixed, governed queries, reruns the engine and drafts the
narrative. It can't change quantities or touch SAP. The planner decides, and every step is recorded in Lakebase for
audit."

**Expected behavior:** the status moves PENDING REVIEW → NEEDS MORE INFO → APPROVED, and the Advisor's
"Human-approved decision" bar now shows 15.

## 23–25 min · Future vision

**Do:** App → *Connected Device Intelligence*. Select `RNI-DEV-0701` (Pinecrest, HIGH priority).

**Say:**
- "The same foundation takes device telemetry. Here a compressor's vibration has been climbing for a week. That's a
  reason to send someone to look, not proof it will fail, and it's prioritized by the critical inventory inside."
- "With ClearBlade data streaming in through Zerobus, the same planners would get these signals in the same case
  workflow."

**Close:** "One governed platform for inventory, forecasting, decision support, conversational analytics and
operations. Built on RNI's own data next."

---

## Fallback assets

| Dependency | If unavailable | Fallback |
|---|---|---|
| Genie API | Ask RNI AI shows the curated-SQL badge | Fixed verified queries (labeled); or open the Genie space UI |
| LLM endpoint | Case summary badge shows `DETERMINISTIC_FALLBACK (non-LLM)` | Template narrative from the same facts |
| Lakebase | Case-store badge shows "DEMO-ONLY local store" | Ephemeral SQLite in the App container |
| SQL warehouse cold start | First load takes 10–30 s | Warm up 5 minutes before |

Take fallback screenshots after the final dry run and save them to `docs/screenshots/`. They can't be captured from
this build environment.

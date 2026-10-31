"""Build the executive walkthrough Word document (docs/RNI_Command_Center_Executive_Walkthrough.docx).

One storyline ("One request, one morning") that walks business users through every App tab and ties all the demo
scenarios together. Figures are the values verified in rni_demo.gold for the as-of date 2026-10-30.
"""
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Inches

NAVY = RGBColor(0x0B, 0x2A, 0x4A)
TEAL = RGBColor(0x0E, 0x8C, 0x8C)
RED = RGBColor(0xB4, 0x23, 0x18)
GREY = RGBColor(0x55, 0x5F, 0x6D)
APP_URL = "https://rni-command-center-1444828305810485.aws.databricksapps.com"
DASH_URL = "https://e2-demo-field-eng.cloud.databricks.com/dashboardsv3/01f1d4e87ddf1efc9a8cb2250a916d0a/published"

doc = Document()
st = doc.styles["Normal"]
st.font.name = "Calibri"
st.font.size = Pt(10.5)
for s in doc.sections:
    s.left_margin = s.right_margin = Inches(0.9)
    s.top_margin = s.bottom_margin = Inches(0.8)


def shade(cell, hex_fill):
    tc = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hex_fill)
    tc.append(sh)


def h(text, level=1):
    p = doc.add_heading(text, level)
    for r in p.runs:
        r.font.color.rgb = NAVY
    return p


def para(text="", bold=False, italic=False, color=None, size=None, after=4):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold, r.italic = bold, italic
    if color:
        r.font.color.rgb = color
    if size:
        r.font.size = Pt(size)
    p.paragraph_format.space_after = Pt(after)
    return p


def rich(parts, style=None):
    """parts: list of (text, bold) tuples."""
    p = doc.add_paragraph(style=style)
    for text, bold in parts:
        p.add_run(text).bold = bold
    p.paragraph_format.space_after = Pt(2)
    return p


def bullets(items, style="List Bullet"):
    for it in items:
        if isinstance(it, tuple):
            rich([(it[0], True), (it[1], False)], style)
        else:
            p = doc.add_paragraph(it, style=style)
            p.paragraph_format.space_after = Pt(2)


def callout(label, text, fill="E6F4F4", color=TEAL):
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.cell(0, 0)
    shade(c, fill)
    p = c.paragraphs[0]
    r = p.add_run(label + "  ")
    r.bold = True
    r.font.color.rgb = color
    p.add_run(text).italic = True
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def say(text):
    callout("SAY:", f"“{text}”", "F2F5F9", NAVY)


def wow(text):
    callout("WOW MOMENT:", text, "FDF1E6", RGBColor(0xC2, 0x5E, 0x00))


def tech(text):
    callout("UNDER THE HOOD:", text, "EAF0FB", RGBColor(0x1F, 0x4E, 0x9A))


def table(header, rows, widths=None, head_fill="0B2A4A"):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, txt in enumerate(header):
        c = t.rows[0].cells[i]
        shade(c, head_fill)
        r = c.paragraphs[0].add_run(txt)
        r.bold = True
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        r.font.size = Pt(9.5)
    for row in rows:
        cells = t.add_row().cells
        for i, txt in enumerate(row):
            r = cells[i].paragraphs[0].add_run(str(txt))
            r.font.size = Pt(9.5)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return t


# ================================================================================================ cover
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.LEFT
r = p.add_run("FFF Enterprises · Right Now Inventory (RNI)")
r.font.color.rgb = TEAL
r.bold = True
r.font.size = Pt(12)
p = doc.add_paragraph()
r = p.add_run("RNI Intelligent Operations Command Center")
r.bold = True
r.font.size = Pt(24)
r.font.color.rgb = NAVY
para("Executive walkthrough: “One request, one morning”", size=15, color=GREY, after=10)
para("A single storyline that takes business users through every tab of the Command Center and ties together all "
     "five demo scenarios. Written for the presenter: what to click, what to say, and where the “wow” lands.",
     after=8)
table(["Item", "Detail"], [
    ["Audience", "RNI business leaders: operations, supply chain, finance, customer success; CIO / EVP sponsors"],
    ["Run time", "20–25 minutes (a 10-minute short cut is at the end)"],
    ["App", APP_URL],
    ["Dashboard (optional opener)", "RNI Executive Inventory Intelligence: " + DASH_URL],
    ["Data", "Synthetic, shaped like RNI operations: 15 fictional sites, 30 products, 24 months. No PHI, no live "
             "RNI / SAP systems. Nothing in the demo creates a shipment or a return."],
    ["Figures in this guide", "Verified in the Gold layer for as-of date 30 Oct 2026. Re-running the data pipeline "
                              "reproduces them exactly."],
], widths=[1.6, 5.0])

# ================================================================================================ story
h("1. The story in one paragraph")
para("It is Tuesday morning at RNI. Overnight, Hospital A submitted a replenishment request for 500 doses of "
     "Product A, a $900-per-dose hyperimmune globulin. Hospital A used one dose in the last four months. Today a planner "
     "would either ship it (and FFF eats the cold-chain return and expiry later) or spend an hour pulling reports to "
     "push back. In the next 20 minutes we follow that one request from the moment it surfaces to the moment a planner "
     "approves the right quantity, and along the way we meet four other sites whose problems look nothing alike, but "
     "are caught by the same engine.")
say("We are going to follow one request — 500 doses for a site that used one — from the morning alert to a signed-off "
    "decision. Everything you see is on one governed platform, and no AI model ever picks the number.")

h("Meet the cast (the five scenarios)", 2)
table(["#", "Site · product", "What's happening", "Request → engine says", "Category the engine assigns"], [
    ["1 (lead)", "Hospital A · Product A (hyperimmune globulin, $900)", "Asked for 500; used 1 in 120 days; on hand 25, "
     "PAR 60, minimum 40", "500 → 15 (simple PAR top-up would say 35)", "Excessive request · $436.5K potential exposure"],
    ["2", "Harbor Point Infusion Center · Corvanta IVIG 10%", "Busy site (361 used in 120 days), only 6 on hand",
     "10 → 25", "Stockout risk: the request is too SMALL"],
    ["3", "Mesa Verde Community Hospital · Crotivane Antivenom", "Rare emergency product; 0 used in 120 days; "
     "on hand 6, minimum 8", "4 → 2", "Critical policy hold: the forecast says ~0, policy keeps the floor"],
    ["4", "Lakeshore Children's Hospital · Oncomab 400 mg", "22 on hand; 14 units expire within 90 days, ~9 projected "
     "to expire unused (~$21K)", "2 → 0", "Expiry risk: rebalance, don't ship"],
    ["5", "Summit Hematology & Oncology · Hemofix Factor VIII", "Already above PAR; returned this SKU 6 times in 12 "
     "months", "90 → 0", "Excessive request · $130.5K exposure, high-returns flag"],
], widths=[0.55, 1.6, 1.85, 1.3, 1.5])
para("The point of the cast: one is too big, one is too small, one must not be cut, one is about to expire, one keeps "
     "coming back. A single rule like “PAR minus on hand” gets most of them wrong.", italic=True, color=GREY)

# ================================================================================================ walkthrough
h("2. The walkthrough, tab by tab")

# ---- Act 0
h("Act 0 · (Optional, 2 min) The executive dashboard: “How big is the problem?”", 2)
rich([("Open: ", True), ("AI/BI dashboard “RNI Executive Inventory Intelligence”.", False)])
bullets([
    ("Point at the six KPI tiles: ", "$3.42M deployed in RNI devices across 15 sites; $1.42M potential excess exposure; "
     "24 shipment requests needing review; $4.83M returned in 12 months; ~$128K avoidable cold-chain logistics."),
    ("Point at “Consumption vs shipments”: ", "the gap between what is shipped and what is used is the inventory that "
     "comes back later as returns and write-offs."),
    ("Filter one region: ", "every tile moves together. Same definitions everywhere; buckets never double count."),
])
say("$1.4 million of potential excess is sitting in, or about to be sent to, customer sites. Let's see where one "
    "piece of it comes from.")

# ---- Act 1
tech("Databricks AI/BI Dashboard on a serverless SQL warehouse, reading Gold views in Unity Catalog (rni_demo.gold). The KPIs are SQL definitions in the Gold layer, so the dashboard, the App and Genie share one version of each number. Global filters drive every tile. [Analytics, not AI/ML.]")

h("Act 1 · Inventory Command Center (3 min): “The morning alert”", 2)
rich([("Open: ", True), ("App → Inventory Command Center.", False)])
bullets([
    ("The red banner: ", "“Potentially excessive request — Hospital A · Product A. Requested 500 · consumed 1 in the last "
     "120 days · on hand 25 vs PAR 60 (minimum 40) · engine recommends 15 · potential exposure $436,500.”"),
    ("Scroll to “High-priority shipment requests for review”: ", "Hospital A is priority 1; Summit Hematology (cast #5) "
     "is right behind at priority 3. Harbor Point, Mesa Verde and Lakeshore are in the same queue for very different "
     "reasons. Name them now; we'll come back to each."),
    ("Top-10 locations chart: ", "excess on hand vs pending-request exposure, so leadership sees which sites drive it."),
])
wow("The system found the problem before anyone opened a spreadsheet: the alert, the evidence and the dollar exposure "
    "are on the home screen.")
rich([("Click: ", True), ("“Open in Intelligent Shipment Advisor →”.", False)])

# ---- Act 2
tech("Databricks App (Streamlit) running as its own service principal with read-only SELECT on the Gold schema. It queries the serverless SQL warehouse through a fixed allow-list of Gold views (no free-form SQL). The red alert and review queue come from gold.shipment_review_queue, written by the decision engine in the Lakeflow job. [Rules engine output surfaced by an App.]")

h("Act 2 · Intelligent Shipment Advisor (6 min): “Why 15, not 500, and not 35”", 2)
para("This is the centerpiece. Slow down here.", italic=True, color=GREY)
bullets([
    ("KPI row: ", "Requested 500 · On hand 25 · PAR 60 · Minimum 40 · Used 1 · Forecast ≈ 0.7 · Recommended 15."),
    ("Four-bar comparison: ", "Original request 500 · PAR-only baseline 35 · Policy-constrained recommendation 15 · "
     "Human-approved decision (pending)."),
    ("Explanation panel (read two lines aloud): ", "“Mandatory minimum (40) sets the target: forecast need (3) is "
     "lower.” and “3 of the 4 units expiring within 90 days are projected to expire unused.” Then: “Recommended = "
     "target 40 − available 25, rounded up to pack size 5 = 15.”"),
    ("Forecast chart: ", "weekly history, forecast and 80% band. The model was chosen by backtest (TSB for sparse "
     "demand), not because it is the fanciest."),
])
say("A simple PAR top-up would ship 35. Shipping 500 creates $436K of exposure. The engine applies the full policy "
    "— forecast, mandatory minimum, expiry, stock in transit, pack size — and lands on 15. Every line of reasoning is on "
    "screen, and the same inputs always give the same answer.")
wow("Each recommendation shows its working, line by line. An auditor, a planner and a customer can all see why.")

h("Tie in the cast live (what-if and product switch)", 3)
table(["Do this in the Advisor", "What the screen shows", "Line to say"], [
    ["What-if: set Mandatory minimum to 60", "Recommendation jumps to 35", "“Policy drives the target. Change the "
     "policy, the answer changes — transparently.”"],
    ["What-if: set Requested to 15", "Excessive flag disappears, but it still routes to review as Critical policy hold "
     "(25 on hand is below the minimum of 40)", "“Even a reasonable request on a critical product below its floor keeps "
     "a human in the loop.”"],
    ["Click Reset", "Back to 500 → 15", ""],
    ["Switch to Harbor Point · Corvanta IVIG (cast #2)", "Request 10 → recommend 25 · Stockout risk", "“This isn't a "
     "tool for saying no. Here the site under-asked; 10 would leave it 14 short before the next delivery.”"],
    ["Switch to Mesa Verde · Crotivane Antivenom (cast #3)", "Forecast ≈ 0.3, yet target is 8 · Critical policy hold · "
     "recommend 2", "“The model says nobody needs antivenom. Policy says you never cut below 8. Policy wins, every "
     "time. Forecasts inform; they never override safety stock.”"],
    ["Switch to Lakeshore · Oncomab (cast #4)", "Recommend 0 · Expiry risk · ~$21K projected to expire unused",
     "“Don't ship more; move what's about to expire to a site that will use it.”"],
    ["Switch to Summit Hematology · Hemofix (cast #5)", "90 → 0 · Excessive · 6 returns in 12 months",
     "“The same pattern as Hospital A at a different site, and this one has a return history to prove it.”"],
], widths=[2.0, 2.3, 2.5])
wow("Five sites, five different answers (more, less, hold the floor, rebalance, decline) from one engine "
    "in under two minutes. That is what “intelligent” means here.")
rich([("Switch back to Hospital A · Product A before moving on.", True)])

# ---- Act 3
tech("ML + deterministic engine. The forecast is MACHINE LEARNING: a Lakeflow (serverless) job classifies every site/product series, backtests six models, picks the best per demand class, tracks every run in MLflow and registers the model in Unity Catalog (rni_demo.ml.rni_demand_forecaster). The quantity (15) is NOT AI: it comes from a deterministic Python decision engine with unit tests; the App reruns it live for the what-ifs, so the answer is reproducible and auditable.")

h("Act 3 · Ask RNI AI (4 min): “Ask it in plain English”", 2)
rich([("Open: ", True), ("App → Ask RNI AI. Click three of the suggested questions:", False)])
bullets([
    "“Why was Hospital A's shipment request flagged?” (ties straight back to Act 2)",
    "“Which customers have the highest excess inventory exposure?”",
    "“How much was returned during the last 12 months?” (should match the $4.83M on the dashboard)",
], "List Number")
bullets([
    ("Point at the green “Live Genie response” badge, ", "then open the SQL it ran."),
    ("If time allows, ask a question of your own audience's choosing, ", "e.g. “Which products may expire in the next "
     "60 days?” — Lakeshore's Oncomab should appear."),
])
say("Genie answers on the same governed tables as the dashboard and the engine — same definitions, same numbers — and "
    "it shows its SQL. No one has to wait for a report to be built.")
wow("A business user asks “why?” in English and gets the same answer the engine gave, with the query behind it.")
para("Expect 15–20 seconds per answer. If Genie is slow, the App switches to verified queries labelled “Curated SQL "
     "fallback — not a Genie response”. Say so out loud; never present it as Genie.", italic=True, color=GREY)

# ---- Act 4
tech("GENERATIVE AI (BI). AI/BI Genie space “RNI Inventory Intelligence Agent” turns English into SQL over 12 curated Gold tables, guided by business definitions, example SQL and benchmark questions (all 8 benchmarks matched verified SQL). The App calls Genie through the Conversation API and badges every answer as live Genie or curated fallback. Unity Catalog permissions apply to every query.")

h("Act 4 · AI Operations Cases (4 min): “From insight to a signed-off decision”", 2)
rich([("Do: ", True), ("Back in the Advisor (Hospital A), click “Create investigation case →”. The case opens in "
                       "AI Operations Cases.", False)])
bullets([
    ("Show the case: ", "AI-written summary, risk explanation, missing information, proposed next action and the "
     "evidence table. The badge shows which model wrote the narrative."),
    ("Choose “Needs more information”, ", "type a comment (e.g. “Confirm with Hospital A pharmacy whether a new protocol "
     "drives the 500 request”) and submit."),
    ("Reopen and Approve ", "with a human-approved quantity of 15. Go back to the Advisor: the fourth bar, "
     "“Human-approved decision”, now shows 15."),
])
say("The assistant gathers the facts and drafts the case, but it cannot change the quantity and it cannot touch SAP. "
    "The planner decides, and every step is recorded for audit.")
wow("The loop closes on screen: alert → explanation → AI-drafted case → human decision → the chart updates. "
    "Pending → Needs more info → Pending → Approved, all logged.")

# ---- Act 5
tech("GENERATIVE AI + LAKEBASE. The case narrative is written by an LLM on Databricks Model Serving (Foundation Model API endpoint databricks-claude-sonnet-4-5). It receives facts gathered by fixed, governed queries and the engine's output, and returns text only — it cannot set quantities. Cases, reviews, overrides and the AI activity log are written to LAKEBASE (managed Postgres) because this is transactional app state: millisecond reads/writes, row updates and status changes that a warehouse is not designed for.")

h("Act 5 · Business Value Simulator (3 min): “What is this worth to us?”", 2)
rich([("Open: ", True), ("App → Business Value Simulator.", False)])
bullets([
    ("Three separate answers, never added together: ", "(1) inventory value released, one-time working capital; "
     "(2) potential annual cost avoidance (returns logistics, expiry, carrying cost, availability); (3) realized cash "
     "savings — deliberately “Not claimed” until validated against FFF finance data."),
    ("Hand the sliders to the room: ", "“What share of excess do you think is avoidable? What does a cold-chain return "
     "really cost you?” Let them set the assumptions."),
])
say("We're not going to tell you a savings number. We'll show you the levers and let your numbers drive it.")
callout("PRESENTER NOTE:", "At the default assumptions this 15-site synthetic network shows ≈ $147K inventory released "
        "and ≈ $82K annual cost avoidance, against a placeholder $250K solution cost, so net benefit is negative. "
        "That is a scale effect of a 15-site demo, not a finding. Do not lead with the net-benefit tile: frame it as "
        "“per 15 sites” and let the audience scale it to the RNI network, or set the solution cost to a per-site share "
        "before the session.", "FBEAEA", RED)
wow("Credibility, not hype: the simulator separates released inventory, cost avoidance and cash, and refuses to claim "
    "cash savings it can't prove.")

# ---- Act 6
tech("Pure Python business logic in the App, fed by Gold KPIs from the SQL warehouse. Deliberately not AI: every figure traces to a formula and a slider. [Analytics.]")

h("Act 6 · Connected Device Intelligence (2 min): “What's next”", 2)
rich([("Open: ", True), ("App → Connected Device Intelligence. Select RNI-DEV-0701 (Pinecrest, HIGH priority).", False)])
bullets([
    "Compressor vibration has been climbing for a week; the anomaly score is sustained, not a one-off spike.",
    "Priority is weighted by the value and criticality of the inventory inside the device.",
])
say("This is a reason to send a technician, not proof the unit will fail. With device telemetry streaming in, the "
    "same planners get these signals in the same case workflow as the shipment requests.")
wow("The RNI cabinet stops being a box of stock and becomes a sensor: inventory, demand and device health on one "
    "platform.")

# ---- Close
tech("Today: synthetic telemetry (15-minute readings) is generated and scored in the Lakeflow job with a statistical anomaly detector, landing in gold.device_health. Tomorrow (not built in this demo): ZEROBUS INGEST streams device events from the cabinets / ClearBlade straight into Unity Catalog Delta tables over gRPC, with no Kafka or message bus to run, and the same scoring and case workflow pick them up in near real time.")

h("Close (1 min)", 2)
say("One request, one morning: we saw the alert, understood why 15 was right and 500 and 35 were wrong, saw the same "
    "engine make five different calls for five different sites, asked questions in English, closed the loop with a "
    "human decision, and sized the value on your assumptions. Next step: the same build on RNI's own data.")

# ================================================================================================ matrix
h("3. How the scenarios tie to the tabs")
table(["Scenario", "Command Center", "Shipment Advisor", "Ask RNI AI", "Cases", "Value / Device"], [
    ["Hospital A · Product A", "Red banner; priority 1 in queue", "Centerpiece: 500 → 15 vs PAR 35; what-ifs",
     "“Why was Hospital A's request flagged?”", "Case created, reviewed, approved at 15", "Drives excess and "
     "pending-request exposure"],
    ["Harbor Point · IVIG", "In review queue", "Too-small request: 10 → 25", "—", "Optional second case", "Availability "
     "margin protected"],
    ["Mesa Verde · Antivenom", "In review queue", "Forecast ≈ 0, floor of 8 holds", "—", "—", "Shows safety-first "
     "policy"],
    ["Lakeshore · Oncomab", "Expiry horizon chart", "Recommend 0; ~$21K to expire unused", "“Which products may expire "
     "in the next 60 days?”", "—", "Expiry losses avoided"],
    ["Summit · Factor VIII", "Priority 3 in queue; top-10 chart", "90 → 0; 6 returns in 12 months",
     "“Which products have the highest return rates?”", "—", "Returns logistics avoided"],
    ["Device RNI-DEV-0701", "—", "—", "—", "—", "Device Intelligence: sustained vibration anomaly"],
], widths=[1.15, 1.1, 1.3, 1.3, 1.0, 1.1])

# ================================================================================================ wow list
h("4. The seven “wow” moments to land")
bullets([
    ("It finds the problem for you: ", "the 500-dose request is on the home screen with its dollar exposure."),
    ("It shows its working: ", "every recommendation explains itself line by line; same inputs, same answer."),
    ("It's smarter than PAR: ", "15, not 35; and it applies forecast, minimum, expiry, in-transit and pack size."),
    ("It says yes as well as no: ", "Harbor Point is told to order more, not less."),
    ("Safety beats the algorithm: ", "the antivenom floor holds even when the forecast says zero."),
    ("Plain-English answers that match: ", "Genie, the dashboard and the engine give the same numbers."),
    ("Humans decide, AI assists, everything is audited: ", "the case loop closes on screen; no SAP action is possible."),
], "List Number")

# ================================================================================================ Q&A
h("5. Likely questions and honest answers")
table(["Question", "Answer"], [
    ["Is the AI choosing the quantity?", "No. A deterministic, tested decision engine computes it. The language model "
     "only drafts the case narrative and cannot change numbers."],
    ["Is this our data?", "No. It is synthetic data shaped like RNI operations (15 fictional sites, 30 products, "
     "24 months). The next step is to run the same build on RNI data."],
    ["How accurate is the forecast?", "It was picked by rolling backtests against simple baselines. For sparse demand "
     "it is slightly worse than a moving average at 30 days and better at 60 and 90. For emergency products we never "
     "rely on the forecast alone: the minimum and human review protect supply."],
    ["Can it ship or cancel orders in SAP?", "No. Nothing in the demo creates, changes or returns a shipment. "
     "Integration would be a deliberate, governed next phase."],
    ["Can Genie run any SQL someone types?", "Genie works only over the curated Gold tables it was given, with "
     "read-only access. The App's own queries are fixed and allow-listed."],
    ["Can returns always be traced to the order that caused them?", "Not always, and the data says so: returns are "
     "linked to a single candidate order, flagged as ambiguous (several possible orders), or unlinked opening stock."],
    ["What would savings be for RNI?", "We don't claim a number. The simulator shows the levers; realized cash savings "
     "need validation against FFF finance data."],
], widths=[2.0, 4.6])

# ================================================================================================ prep
# ================================================================================================ technical
h("6. Under the hood: how each capability maps to Databricks")
para("Use this section when the audience asks “how does it work?” or for a technical follow-up. The one-line rule: "
     "ML forecasts demand, rules decide quantities, generative AI explains and answers questions, and humans approve.",
     italic=True, color=GREY)

h("6.1 Where we use AI, ML and plain rules", 2)
table(["Capability", "Type", "Databricks feature", "Why this choice", "Guardrail"], [
    ["Demand forecast (30/60/90 days, 80% range)", "Machine learning (statistical time-series)",
     "Lakeflow Jobs (serverless) · MLflow experiment tracking · model registered in Unity Catalog",
     "Six models compared on rolling backtests; best per demand pattern (seasonal for steady demand, TSB for sparse "
     "demand)", "Leakage test; intervals calibrated; forecast can never pull stock below the minimum"],
    ["Recommended quantity (e.g. 15)", "Deterministic rules engine (not AI)", "Python engine run in the Lakeflow job; "
     "re-run live in the Databricks App for what-ifs", "Quantities must be exact, explainable and repeatable",
     "Unit tested; same inputs → same answer; every step written to the explanation"],
    ["Risk flags (excessive, stockout, expiry, critical hold)", "Rules on top of ML output", "Same engine; results "
     "in Gold tables in Unity Catalog", "Business thresholds are policy, set in config", "Thresholds visible and "
     "versioned in Git"],
    ["Ask RNI AI", "Generative AI (text-to-SQL)", "AI/BI Genie space + Genie Conversation API",
     "Business users ask in English; answers stay on governed data", "Only 12 curated Gold tables; read-only; SQL "
     "shown; benchmarked; labelled fallback"],
    ["Case summary & next action", "Generative AI (LLM narrative)", "Model Serving · Foundation Model API "
     "(databricks-claude-sonnet-4-5)", "Saves planners the write-up", "Facts come from fixed queries; LLM returns "
     "text only; cannot change quantities or call SAP; template fallback"],
    ["Device anomaly score", "Statistical anomaly detection", "Lakeflow job → Gold table device_health",
     "Spot sustained drift, not one-off spikes", "Positioned as “inspect”, not “will fail”"],
    ["Business value", "Formulas", "Databricks App (Python)", "Finance needs traceable numbers", "Cash savings "
     "never claimed"],
], widths=[1.3, 1.05, 1.6, 1.4, 1.35])

h("6.2 Databricks features behind each tab", 2)
table(["Tab / step", "Databricks features in play"], [
    ["Executive dashboard", "AI/BI Dashboards · serverless SQL warehouse · Unity Catalog Gold views"],
    ["Inventory Command Center", "Databricks Apps (Streamlit, own service principal) · SQL warehouse · Unity Catalog "
     "least-privilege grants (SELECT on Gold only)"],
    ["Intelligent Shipment Advisor", "Decision engine output from Lakeflow Jobs · forecasts from the MLflow-tracked "
     "pipeline · live engine re-run inside the App"],
    ["Ask RNI AI", "AI/BI Genie (space with instructions, example SQL, benchmarks) · Genie Conversation API"],
    ["AI Operations Cases", "Model Serving (Foundation Model API) for the narrative · Lakebase Postgres for case "
     "state and audit trail"],
    ["Business Value Simulator", "Databricks Apps · Gold KPI table"],
    ["Connected Device Intelligence", "Lakeflow job scoring · Gold device tables · (roadmap) Zerobus Ingest"],
    ["Behind all tabs", "Unity Catalog (governance, lineage, PK/CHECK constraints, volume for landing files) · "
     "Declarative Automation Bundles (one command deploys job, App and Lakebase to dev or demo) · Git"],
], widths=[1.9, 4.7])

h("6.3 End-to-end flow", 2)
bullets([
    ("Land: ", "synthetic RNI-shaped files (sites, products, PAR rules, orders, lots, consumption, returns, telemetry) "
     "land in a Unity Catalog volume → Bronze."),
    ("Conform: ", "loaded to Silver Delta tables with primary keys and CHECK constraints; a lot-level ledger "
     "reconciles to on-hand stock (69 integrity checks)."),
    ("Forecast (ML): ", "the forecasting task backtests and selects models, logs to MLflow and registers the model in "
     "Unity Catalog; forecasts are written to the ml schema."),
    ("Decide (rules): ", "the decision engine scores every pending request and every site/product cycle review, "
     "writing recommendations, explanations and risk flags."),
    ("Serve: ", "Gold views and KPI tables feed the dashboard, Genie and the App from one set of definitions."),
    ("Act: ", "the App drafts cases with the LLM, planners decide, and Lakebase records every case, review, override "
     "and AI action."),
    ("Prove: ", "62 automated tests run as the last task of the same job, against the live tables."),
], "List Number")
para("All six steps run as one serverless Lakeflow job (rni-command-center-data-pipeline), deployed by the bundle.",
     italic=True, color=GREY)

h("6.4 Where Lakebase helps", 2)
para("The Gold layer answers analytical questions over millions of rows. A review workflow needs something different: "
     "small, frequent, transactional writes with instant read-back. That is what Lakebase (managed, serverless "
     "Postgres inside Databricks) is for.")
table(["What Lakebase stores (schema rni_ops)", "Why it belongs in Lakebase"], [
    ["investigation_cases: one row per case, updated as status changes", "Row-level updates and low-latency reads "
     "while the planner clicks"],
    ["planner_reviews: every status change with reviewer and comment", "Append-only audit trail with transactions"],
    ["decision_overrides: engine quantity vs human-approved quantity", "Shows where and why people overrode the "
     "engine; feeds model and policy tuning"],
    ["agent_activity: every AI action (facts gathered, narrative generated)", "Accountability for AI: what it did, "
     "when, on whose behalf"],
    ["user_feedback: ratings on answers", "Improves Genie instructions and prompts over time"],
], widths=[3.2, 3.4])
bullets([
    ("Operational benefits: ", "autoscaling 0.5–1 CU and scale-to-zero after 10 minutes idle (pay only while used); "
     "the App connects with short-lived OAuth credentials from its service principal, so no database passwords exist."),
    ("Why not just Delta tables? ", "Delta is excellent for analytics, but per-click single-row updates from an App are "
     "a transactional (OLTP) pattern. Lakebase keeps both on one platform, governed together; case history can be "
     "synced back to Unity Catalog for reporting on reviewer decisions."),
    ("Resilience: ", "if Lakebase is unavailable the App says so and uses a clearly labelled demo-only store, so the "
     "demo never breaks."),
])

h("6.5 Where Zerobus Ingest fits (roadmap, not in this demo)", 2)
callout("BE CLEAR:", "Zerobus is not running in this build. Device telemetry today is synthetic and processed in the "
        "batch job. Present Zerobus as the production path for live cabinet data.", "FBEAEA", RED)
bullets([
    ("What it is: ", "Zerobus Ingest lets producers (devices, gateways, services) write records directly into Unity "
     "Catalog Delta tables over gRPC, in near real time, without running Kafka or another message bus."),
    ("How it would work for RNI: ", "RNI cabinet events (temperature, door open, compressor vibration, dispense / "
     "restock scans) → ClearBlade or the device gateway → Zerobus Ingest → Bronze Delta table in Unity Catalog → "
     "streaming scoring (Lakeflow) → Gold device_health and on-hand updates → the same App screens and case workflow."),
    ("Why it matters to the business: ", "temperature excursions and device faults reach planners in minutes, "
     "prioritised by the value and criticality of stock inside; dispense scans would make on-hand and consumption "
     "near real time, which sharpens the forecast and the shipment decision."),
    ("Why it matters to IT: ", "one fewer system to run (no message bus), governance from the first record, and "
     "the same lineage and permissions as the rest of the data."),
])

h("6.6 Governance and safety built in", 2)
bullets([
    "Everything lives in one Unity Catalog catalog (rni_demo: bronze, silver, ml, gold) with lineage from raw file to "
    "dashboard tile.",
    "The App runs as its own service principal with SELECT on Gold only; no credentials in code; resources injected "
    "at deploy time.",
    "No free-form SQL from AI: the App's queries are a fixed allow-list; Genie is limited to curated Gold tables and "
    "shows its SQL.",
    "AI never picks a quantity and no action can create, change or return a shipment in SAP.",
    "Every AI answer is labelled with its source (live Genie, LLM endpoint, or fallback).",
    "Reproducible: the data, forecasts and recommendations regenerate identically from the job; 62 tests pass.",
])

h("7. Presenter checklist")
bullets([
    "15 minutes before: open the App and click through every tab once, and open the dashboard, so the SQL warehouse "
    "and the case store are warm (first load can take 10–30 seconds).",
    "Make sure the App is running (Compute → Apps → rni-command-center). Stop it after the session.",
    "Do one dry run of Act 4 the day before so you know how the case screen looks; cases from rehearsals stay in the "
    "list, which is fine — or point at the newest one.",
    "Decide in advance how you'll present the Business Value net-benefit tile (see the note in Act 5).",
    "Have the Genie space open in a spare browser tab as a backup for Act 3.",
    "In the dry run, confirm the badges: Ask RNI AI shows “Live Genie response”, the case summary names the model "
    "endpoint, and the case store shows Lakebase (not the demo-only store).",
    "Say the ground rule at the start: synthetic data, no live RNI or SAP systems, nothing creates a shipment or a return.",
])

h("10-minute short cut", 2)
bullets([
    "Act 1 (alert) → Act 2 (Hospital A + one switch to Mesa Verde antivenom) → Act 3 (one Genie question) → "
    "Act 4 (create and approve the case). Skip the dashboard, value simulator and devices.",
])

out = Path(__file__).resolve().parents[1] / "docs" / "RNI_Command_Center_Executive_Walkthrough.docx"
doc.save(out)
print(out)

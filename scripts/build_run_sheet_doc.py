"""Build the demo-day run sheet Word document (docs/RNI_Demo_Day_Run_Sheet.docx).

Click-by-click execution for the executive demo: timings, pre-demo checklist, what the screen should show, what to
say, the "wow" beat for each step, and a recovery playbook. Figures are the values verified in rni_demo.gold for
the as-of date 2026-10-30.
"""
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

NAVY = RGBColor(0x0B, 0x2A, 0x4A)
TEAL = RGBColor(0x0E, 0x8C, 0x8C)
RED = RGBColor(0xB4, 0x23, 0x18)
ORANGE = RGBColor(0xC2, 0x5E, 0x00)
BLUE = RGBColor(0x1F, 0x4E, 0x9A)
GREY = RGBColor(0x55, 0x5F, 0x6D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
APP_URL = "https://rni-command-center-1444828305810485.aws.databricksapps.com"
DASH_URL = "https://e2-demo-field-eng.cloud.databricks.com/dashboardsv3/01f1d4e87ddf1efc9a8cb2250a916d0a/published"
GENIE_URL = "https://e2-demo-field-eng.cloud.databricks.com/genie/rooms/01f1d4e83ebe1ea089da3d55bd01592f"

doc = Document()
doc.styles["Normal"].font.name = "Calibri"
doc.styles["Normal"].font.size = Pt(10.5)
for s in doc.sections:
    s.left_margin = s.right_margin = Inches(0.85)
    s.top_margin = s.bottom_margin = Inches(0.75)


def shade(cell, fill):
    pr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), fill)
    pr.append(sh)


def h(text, level=1):
    p = doc.add_heading(text, level)
    for r in p.runs:
        r.font.color.rgb = NAVY


def para(text, bold=False, italic=False, color=None, size=None, after=4):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold, r.italic = bold, italic
    if color:
        r.font.color.rgb = color
    if size:
        r.font.size = Pt(size)
    p.paragraph_format.space_after = Pt(after)


def bullets(items, style="List Bullet"):
    for it in items:
        p = doc.add_paragraph(style=style)
        if isinstance(it, tuple):
            p.add_run(it[0]).bold = True
            p.add_run(it[1])
        else:
            p.add_run(it)
        p.paragraph_format.space_after = Pt(2)


def gap():
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def table(header, rows, widths, head_fill="0B2A4A", size=9.5):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, txt in enumerate(header):
        c = t.rows[0].cells[i]
        shade(c, head_fill)
        r = c.paragraphs[0].add_run(txt)
        r.bold, r.font.size = True, Pt(size)
        r.font.color.rgb = WHITE
    for row in rows:
        cells = t.add_row().cells
        for i, txt in enumerate(row):
            r = cells[i].paragraphs[0].add_run(str(txt))
            r.font.size = Pt(size)
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Inches(w)
    gap()


def step(num, title, minutes, click, see, say, wow=None, recover=None, tip=None):
    """One demo step as a labelled block: CLICK / YOU'LL SEE / SAY / WOW / IF IT GOES WRONG."""
    h(f"Step {num} · {title}  ({minutes})", 2)
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    blocks = [("CLICK", click, "EEF2F7", NAVY), ("YOU'LL SEE", see, "FFFFFF", GREY),
              ("SAY", say, "F2F5F9", NAVY)]
    if wow:
        blocks.append(("WOW", wow, "FDF1E6", ORANGE))
    if tip:
        blocks.append(("TIP", tip, "EAF0FB", BLUE))
    if recover:
        blocks.append(("IF IT GOES WRONG", recover, "FBEAEA", RED))
    for label, body, fill, color in blocks:
        cells = t.add_row().cells
        shade(cells[0], fill)
        shade(cells[1], fill)
        r = cells[0].paragraphs[0].add_run(label)
        r.bold, r.font.size = True, Pt(9)
        r.font.color.rgb = color
        items = body if isinstance(body, list) else [body]
        first = True
        for it in items:
            p = cells[1].paragraphs[0] if first else cells[1].add_paragraph()
            first = False
            txt = f"“{it}”" if label == "SAY" else it
            run = p.add_run(("• " if len(items) > 1 else "") + txt)
            run.font.size = Pt(9.5)
            run.italic = label == "SAY"
    for row in t.rows:
        row.cells[0].width = Inches(1.25)
        row.cells[1].width = Inches(5.55)
    gap()


# ================================================================================================ cover
p = doc.add_paragraph()
r = p.add_run("FFF Enterprises · Right Now Inventory (RNI)")
r.bold, r.font.size = True, Pt(12)
r.font.color.rgb = TEAL
p = doc.add_paragraph()
r = p.add_run("Demo Day Run Sheet")
r.bold, r.font.size = True, Pt(26)
r.font.color.rgb = NAVY
para("RNI Intelligent Operations Command Center — step-by-step execution for the executive session", size=13,
     color=GREY, after=10)
para("How to use this: keep it open on a second screen or printed. Each step tells you exactly what to click, what "
     "should appear (with the real numbers), what to say, and where the “wow” lands. Red boxes tell you how to "
     "recover if something misbehaves.", after=8)
table(["Item", "Detail"], [
    ["App", APP_URL],
    ["Dashboard", DASH_URL],
    ["Genie space (backup)", GENIE_URL],
    ["Lead scenario", "Desert Crest Medical Center (Phoenix, AZ) · Hyperimmune Globulin 1,500 IU · $900 a dose"],
    ["Data", "Synthetic, shaped like RNI operations: 15 fictional sites, 30 products, 24 months, as of 30 Oct 2026. "
             "No PHI. No live RNI or SAP systems; nothing creates a shipment or a return."],
], [1.6, 5.2])

# ================================================================================================ at a glance
h("1. The demo at a glance (25 minutes)")
table(["#", "Time", "Screen", "The point executives take away"], [
    ["0", "0:00", "Opening", "Ground rules; one request, one morning"],
    ["1", "0:01", "AI/BI Dashboard", "$3.42M deployed, $1.42M potential excess, $4.83M returned in 12 months"],
    ["2", "0:03", "Inventory Command Center", "The system finds the 500-dose problem for you"],
    ["3", "0:05", "Intelligent Shipment Advisor", "15, not 500 and not 35 — and it shows its working"],
    ["4", "0:09", "Advisor: what-ifs", "Policy drives the answer, transparently"],
    ["5", "0:11", "Advisor: switch sites", "Five sites, five different calls from one engine"],
    ["6", "0:14", "Ask RNI AI", "Plain-English questions, governed answers, SQL visible"],
    ["7", "0:18", "AI Operations Cases", "AI drafts, a human decides, everything is audited"],
    ["8", "0:21", "Business Value Simulator", "Their assumptions, not our claims"],
    ["9", "0:23", "Connected Device Intelligence", "The cabinet becomes a sensor"],
    ["10", "0:24", "Close", "One platform; next step is RNI's own data"],
], [0.35, 0.55, 1.9, 4.0])

# ================================================================================================ checklist
h("2. Before the demo")
h("The day before", 2)
bullets([
    "Do one full dry run of steps 1–10 at presentation zoom on the screen you'll present from.",
    "Take backup screenshots of every step (especially steps 3, 6 and 7) and keep them in a slide deck.",
    "Confirm the three source badges during the dry run: Ask RNI AI shows “Live Genie response”; a new case’s "
    "summary badge names the model endpoint; the case-store badge says “Lakebase Postgres”.",
    "Decide how you'll handle the Business Value net-benefit tile (see step 8).",
])
h("30 minutes before", 2)
bullets([
    ("Start the App if it was stopped: ", "databricks apps start rni-command-center (takes 2–5 minutes)."),
    ("Warm everything: ", "open the dashboard and click through every App tab once. The first load after idle can "
     "take 10–30 seconds; it's instant afterwards."),
    ("Clear old cases: ", "AI Operations Cases → scroll to the bottom → Administration → type RESET → Reset Cases. "
     "The case list should show (0)."),
    ("Ask one Genie question ", "(any suggested one) so the Genie space is awake."),
])
h("5 minutes before", 2)
bullets([
    "Browser tabs, in order: (1) Dashboard, (2) App on Inventory Command Center, (3) Genie space as backup.",
    "Browser zoom 110–125% so the back row can read the numbers; hide bookmarks bar; full screen.",
    "Silence Slack, email and calendar pop-ups. Close other tabs.",
    "Have this run sheet on a second screen.",
])

# ================================================================================================ steps
h("3. Step-by-step execution")

step(0, "Opening", "1 min",
     click="Nothing yet — stay on the dashboard tab.",
     see="The RNI Executive Inventory Intelligence dashboard.",
     say=["Everything you'll see runs on synthetic data shaped like RNI's operations. No live RNI or SAP systems are "
          "touched, and nothing we do today creates a shipment or a return.",
          "We're going to follow one request — 500 doses for a hospital that used one — from the morning alert to a "
          "signed-off decision."])

step(1, "Executive dashboard: how big is the problem?", "2 min",
     click=["Point at the six KPI tiles, left to right.",
            "Point at the ‘Consumption vs shipments’ chart.",
            "Apply the Region filter = Southwest, then clear it."],
     see=["Inventory deployed $3.42M · Potential excess exposure $1.42M · Requests needing review 24 · Returns (12 mo) "
          "$4.83M · Avoidable logistics ≈ $128K.",
          "Every tile changes together when you filter."],
     say=["About $3.4 million of product sits in RNI cabinets across 15 sites. $1.4 million of it is potential excess — "
          "stock above PAR plus what pending requests would add beyond need. That's exposure, not savings.",
          "The gap between what we ship and what sites use is what comes back later as returns: $4.8 million in the "
          "last year."],
     wow="One filter, every number moves consistently — one set of definitions under the dashboard, the App and Genie.",
     recover="If a tile spins for more than 30 seconds, the warehouse is waking up. Talk through the slide-level "
             "numbers above, then refresh.")

step(2, "Inventory Command Center: the morning alert", "2 min",
     click=["Switch to the App tab (Inventory Command Center).",
            "Read the red banner aloud.",
            "Scroll briefly to ‘High-priority shipment requests for review’, then back up.",
            "Click ‘Open in Intelligent Shipment Advisor →’."],
     see=["Red banner: “Potentially excessive request — Desert Crest Medical Center · Hyperimmune Globulin 1,500 IU. "
          "Requested 500 doses · consumed 1 in the last 120 days · on hand 25 vs PAR 60 (minimum 40) · engine "
          "recommends 15 · potential exposure $436,500.”",
          "Review queue: Desert Crest is priority 1; Summit Hematology priority 3."],
     say="Overnight Desert Crest asked for 500 doses of a $900 emergency biologic. They used one dose in four months. "
         "Nobody had to build a report to find this — it's the first thing on the screen.",
     wow="The problem, the evidence and the dollar exposure are on the home screen before anyone opens a spreadsheet.",
     recover="If the banner is missing, the page loaded before the data: refresh once. If still missing, open the "
             "Shipment Advisor tab and select Desert Crest Medical Center + Hyperimmune Globulin 1,500 IU manually.")

step(3, "Intelligent Shipment Advisor: why 15", "4 min",
     click=["Pause on the KPI row.",
            "Point at the four bars on the left chart.",
            "Point at the forecast chart on the right.",
            "Scroll to ‘Why this recommendation’ and read three lines aloud: the coverage window, the minimum, and the "
            "final calculation."],
     see=["KPI row: 500 original request · 25 on hand · 60 · 40 (PAR · minimum, CRITICAL_MINIMUM_HOLD) · 1 historical "
          "consumption · 0.7 forecast (80% range 0.0–2.2) · 15 recommended (PAR-only baseline 35).",
          "Bars: Original request 500 · PAR-only baseline 35 · Policy-constrained recommendation 15 · Human-approved "
          "decision ‘pending’.",
          "Chart: 2 years of weekly use (14 weeks with any use) and a flat forecast line near 0.16 a week.",
          "Explanation ends: “Recommended = max(0, target 40 − effective available 25) rounded up to pack size 5 = 15.”"],
     say=["A simple PAR top-up would ship 35. The engine applies the whole policy — forecast, the mandatory minimum, "
          "expiry, stock in transit and pack size — and lands on 15.",
          "The forecast says they need less than one dose in the next ten days. For an emergency drug we don't trust "
          "the forecast alone, so it plans for the worst week they've ever had: 3 doses. The hospital's agreed floor "
          "is 40, so the floor wins. They hold 25, so we ship 15.",
          "Shipping 500 would put $436,000 of product at risk of a cold-chain return or expiry.",
          "No AI model picked that number. It's a tested rules engine — same inputs, same answer, every time."],
     wow="Every recommendation shows its working, line by line. An auditor, a planner and the hospital can all see why.",
     tip="If asked “what's the 0.7?”: the tile is the expected use over 30 days. The 0.7 in the explanation is the "
         "high end over the 10-day coverage window. Same rounding, different numbers — see Appendix A.")

step(4, "What-ifs: policy drives the answer", "2 min",
     click=["Set ‘Mandatory minimum’ to 60.",
            "Click Reset, then set ‘Requested quantity’ to 15.",
            "Click Reset."],
     see=["Minimum 60 → recommendation becomes 35.",
          "Request 15 → the EXCESSIVE flag disappears, but it still routes to review as CRITICAL POLICY HOLD (25 on hand "
          "is below the minimum of 40 on a critical product).",
          "Reset → back to 500 → 15."],
     say=["Change the policy and the answer changes — transparently.",
          "Even a sensible request goes to a human when a critical product is below its floor."],
     wow="Executives see the engine respond live to the levers they own.",
     recover="If a number looks odd after several changes, click Reset and redo the single change.")

step(5, "Switch sites: five problems, one engine", "3 min",
     click="Use the Customer and Product selectors at the top of the Advisor, in this order:",
     see=["Harbor Point Infusion Center · Corvanta IVIG 10% 10 g → request 10, recommend 25 · STOCKOUT RISK.",
          "Mesa Verde Community Hospital · Crotivane Antivenom → request 4, recommend 2 · CRITICAL POLICY HOLD "
          "(forecast ≈ 0, floor of 8 holds).",
          "Lakeshore Children's Hospital · Oncomab 400 mg → request 2, recommend 0 · EXPIRY RISK (~$21K projected to "
          "expire unused).",
          "Summit Hematology & Oncology Associates · Hemofix Factor VIII 2,000 IU → request 90, recommend 0 · "
          "EXCESSIVE (6 returns in 12 months).",
          "Then switch back to Desert Crest Medical Center · Hyperimmune Globulin 1,500 IU."],
     say=["Harbor Point: this isn't a tool for saying no — they under-asked and would run short before the next delivery.",
          "Mesa Verde: the model says nobody needs antivenom. Policy says never below 8. Policy wins, every time.",
          "Lakeshore: don't ship more; move what's about to expire to a site that will use it.",
          "Summit: same pattern as Desert Crest, and this site has the return history to prove it."],
     wow="More, less, hold the floor, rebalance, decline — five different answers from one engine in about two minutes.",
     tip="If short on time, show only Mesa Verde (the safety story) and go back to Desert Crest.")

step(6, "Ask RNI AI: questions in plain English", "4 min",
     click=["Open the Ask RNI AI tab.",
            "Click: “Why was Desert Crest's shipment request flagged?”",
            "Click: “Which customers have the highest excess inventory exposure?”",
            "Click: “How much was returned during the last 12 months?”",
            "On one answer, expand the SQL."],
     see=["Each answer takes about 15–25 seconds and shows a green ‘Live Genie response’ badge, a table, a chart and "
          "the SQL Genie ran.",
          "The Desert Crest answer shows requested 500, recommended 15, PAR-only 35.",
          "The returns answer matches the dashboard: ≈ $4.83M."],
     say=["Genie answers on the same governed tables as the dashboard and the engine — same definitions, same numbers — "
          "and it shows its work.",
          "Nobody had to wait for a report to be built."],
     wow="A business user asks “why?” in English and gets the same answer the engine gave, with the query behind it.",
     tip="Fill the 15–25 second wait: “It's writing SQL against our governed Gold tables right now — no data leaves "
         "the platform.”",
     recover="If an answer shows the grey ‘Curated SQL fallback — not a Genie response’ badge, say so plainly: "
             "“Genie is slow right now, so the App is showing the verified query instead.” Or switch to the Genie "
             "tab and ask there. Never present the fallback as Genie.")

step(7, "AI Operations Cases: from insight to a signed-off decision", "3 min",
     click=["Go back to the Shipment Advisor (Desert Crest) and click ‘Create investigation case →’.",
            "On the case: choose Decision = ‘Needs More Info’, type a comment such as “Confirm with Desert Crest "
            "pharmacy whether a new protocol drives the 500 request”, Submit review.",
            "The case stays open: choose Decision = ‘Approved’, Human-approved quantity = 15, comment “Confirmed with site; "
            "approve 15”, Submit review.",
            "Return to the Shipment Advisor."],
     see=["New case, status PENDING, with an AI-generated summary (badge names the model endpoint), risk explanation, "
          "missing information, proposed next action and an evidence table.",
          "Status moves PENDING REVIEW → NEEDS MORE INFO → APPROVED; ‘SAP action: NONE’ is shown on the case.",
          "Back in the Advisor, the fourth bar ‘Human-approved decision’ now shows 15."],
     say=["The assistant gathers the facts through fixed, governed queries, reruns the engine and drafts the case. It "
          "cannot change the quantity and it cannot touch SAP.",
          "The planner decides, and every step is recorded for audit."],
     wow="The loop closes on screen: alert → explanation → AI-drafted case → human decision → the chart updates.",
     recover=["If the summary badge says DETERMINISTIC_FALLBACK, the LLM endpoint didn't respond; the narrative is a "
              "template from the same facts. Say so and carry on — the workflow is identical.",
              "If the case-store badge says ‘DEMO-ONLY local store’, Lakebase isn't connected; the workflow still works "
              "for the session."])

step(8, "Business Value Simulator: what is this worth?", "2 min",
     click=["Open Business Value Simulator.",
            "Point at the three sections: inventory released, potential annual cost avoidance, realized cash savings "
            "(“Not claimed”).",
            "Invite the room to move one slider (e.g. ‘Share of excess allocation considered avoidable’)."],
     see="At the default assumptions: ≈ $147K inventory value released (one-time) and ≈ $82K potential annual cost "
         "avoidance for this 15-site network. Realized cash savings: “Not claimed”.",
     say="We're not going to tell you a savings number. Here are the levers — use your numbers.",
     wow="Credibility: released inventory, cost avoidance and cash are kept separate, and it refuses to claim cash "
         "it can't prove.",
     tip="The net-benefit tile compares against a placeholder $250K solution cost and is negative for a 15-site demo "
         "network. Don't lead with it. Either frame everything as “for these 15 sites” or lower ‘Annual solution "
         "cost’ to a per-site share before the session.")

step(9, "Connected Device Intelligence: what's next", "1 min",
     click=["Open Connected Device Intelligence.",
            "Select device RNI-DEV-0701 (Pinecrest, HIGH priority)."],
     see="Compressor vibration trending up for about a week; sustained anomaly score; inspection priority weighted by "
         "the value and criticality of stock inside.",
     say="This is a reason to send a technician, not proof the unit will fail. With live device data streaming in "
         "through Zerobus, planners would get these signals in the same case workflow.",
     wow="The RNI cabinet stops being a box of stock and becomes a sensor.",
     tip="Telemetry here is synthetic and batch-scored. Zerobus is the production path, not part of this build — "
         "don't imply it is live.")

step(10, "Close", "1 min",
     click="Go back to the Inventory Command Center home screen.",
     see="The Desert Crest banner.",
     say="One request, one morning: we found it, understood why 15 was right and 500 and 35 were wrong, saw the same "
         "engine make five different calls, asked questions in English, and closed the loop with a human decision. "
         "Next step: the same build on RNI's own data.")

# ================================================================================================ recovery
h("4. Recovery playbook")
table(["Symptom", "Likely cause", "What to do and say"], [
    ["App URL shows an error or ‘app not running’", "App was stopped", "Switch to backup screenshots; in parallel run "
     "databricks apps start rni-command-center (2–5 min)."],
    ["Charts spin 10–30 s on first click", "SQL warehouse waking up", "Keep talking; it's instant afterwards. Prevent "
     "by warming 30 minutes before."],
    ["Grey ‘Curated SQL fallback’ badge in Ask RNI AI", "Genie slow or unavailable", "Say it's the verified query, "
     "not Genie; or ask in the Genie tab."],
    ["Case summary says DETERMINISTIC_FALLBACK", "LLM endpoint didn't respond", "Say the narrative is a template "
     "from the same facts; continue."],
    ["Case store says ‘DEMO-ONLY local store’", "Lakebase not connected", "Continue; cases work for the session but "
     "aren't kept after a restart."],
    ["Old rehearsal cases in the list", "Reset not run", "Administration → type RESET → Reset Cases (takes a second)."],
    ["Advisor numbers look wrong after what-ifs", "Controls left changed", "Click Reset."],
], [1.9, 1.5, 3.4])

h("5. After the demo")
bullets([
    "AI Operations Cases → Administration → Reset Cases, so the next session starts clean.",
    "Stop the App to save cost: databricks apps stop rni-command-center. Lakebase scales to zero on its own.",
    "Note any questions you couldn't answer for the follow-up.",
])

# ================================================================================================ appendix A
h("Appendix A · How the Desert Crest numbers are calculated")
table(["Number on screen", "Where it comes from"], [
    ["Consumed 1 in the last 120 days", "Usage records: one dose on 28 Aug 2026. Over two years the site used 21 doses "
     "in 14 of 104 weeks."],
    ["Demand class INTERMITTENT, model TSB", "Demand is rare but steady in size when it happens. The pipeline backtested "
     "six models and TSB was most accurate for this pattern."],
    ["Forecast 0.7 (80% range 0.0–2.2)", "TSB forecasts how often a week has demand and how much: ≈ 0.163 doses a week "
     "→ 0.699 over 30 days. The range comes from resampling the site's own weeks, widened by past forecast error."],
    ["PAR 60 · minimum 40", "Inputs from the site's stocking agreement (simulated contract, effective 1 Nov 2024), "
     "with product policy CRITICAL_MINIMUM_HOLD."],
    ["Coverage window 10 days", "7-day review cycle + 3-day delivery to Phoenix: today's stock must last until the "
     "next delivery could arrive."],
    ["Forecast over window ≈ 0.2 (upper 0.7)", "The 30-day forecast scaled to 10 days; the engine plans to the upper "
     "end."],
    ["Critical uplift to 3", "Emergency product: plan for the largest single week ever seen (3 doses, Nov 2024 and "
     "Nov 2025)."],
    ["Target 40", "max(minimum 40, min(PAR 60, 3)) — the floor wins."],
    ["Effective available 25", "25 on hand + 0 in transit − 0 expiring within the 10-day window (earliest lot "
     "expires in 52 days)."],
    ["3 of 4 units projected to expire", "Lot of 4 expires in 52 days; at ≈ 0.163 a week only about 1 is used first. "
     "Flagged for rebalancing (≈ $2,700)."],
    ["Recommended 15", "40 − 25 = 15, already a multiple of the 5-dose pack."],
    ["PAR-only baseline 35", "60 − 25: what a simple spreadsheet rule would ship."],
    ["Excessive", "500 is more than double the recommendation and would leave ~22,500 days of forecast demand on hand."],
    ["Potential exposure $436,500", "(500 − 15) × $900."],
], [2.2, 4.6])
para("Likely question: “If 3 doses will expire, why count all 25 as available?” — They are usable for the next 10 days, "
     "which is all this shipment has to cover. The engine flags them for rebalancing rather than shipping 3 extra "
     "doses that would also sit unused.", italic=True, color=GREY)

# ================================================================================================ appendix B
h("Appendix B · Databricks features behind each step")
table(["Step", "Databricks capability", "AI, ML or rules?"], [
    ["1 Dashboard", "AI/BI Dashboards · serverless SQL warehouse · Unity Catalog Gold views", "Analytics"],
    ["2 Command Center", "Databricks Apps (own service principal, read-only on Gold) · SQL warehouse", "Rules output"],
    ["3–5 Advisor", "Forecasts from a Lakeflow job tracked in MLflow, model registered in Unity Catalog · decision "
     "engine re-run live in the App", "ML forecast + deterministic rules"],
    ["6 Ask RNI AI", "AI/BI Genie space over 12 curated Gold tables · Genie Conversation API", "Generative AI "
     "(text-to-SQL)"],
    ["7 Cases", "Model Serving · Foundation Model API (narrative only) · Lakebase Postgres for cases and audit trail",
     "Generative AI + transactional store"],
    ["8 Business Value", "Databricks Apps · Gold KPI table", "Formulas"],
    ["9 Devices", "Lakeflow job anomaly scoring · (roadmap) Zerobus Ingest for live device streams", "Statistical "
     "anomaly detection"],
    ["All", "Unity Catalog governance and lineage · Declarative Automation Bundles · Git", "—"],
], [1.4, 3.9, 1.5])

out = Path(__file__).resolve().parents[1] / "docs" / "RNI_Demo_Day_Run_Sheet.docx"
doc.save(out)
print(out)

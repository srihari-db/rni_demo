"""Case workflow, guardrails (no unauthorized writes), shared Gold definitions, and the 500-dose E2E smoke test."""
import ast
import json
import re
from pathlib import Path

import pytest

from conftest import CATALOG, LIVE, ROOT
from src.agents.cases import (APPROVED, NEEDS_INFO, PENDING, REJECTED, InvalidTransition, InvestigationCase,
                              Unauthorized, transition)
from src.data.warehouse import APPROVED_GOLD_OBJECTS, QUERY_SPECS, render_sql
from src.genie.space_config import EXAMPLE_SQL, GENIE_TABLES, serialized_space


def _case(**kw):
    d = dict(customer_id="CUST-001", customer_name="Hospital A", sku="SKU-1001", product_name="Product A",
             requested_qty=500, recommended_qty=15, risk_category="EXCESSIVE_REQUEST", evidence={}, ai_summary="s",
             risk_explanation="r", proposed_next_action="a", missing_information=[], summary_source="DETERMINISTIC_FALLBACK",
             created_by="planner@x")
    d.update(kw)
    return InvestigationCase(**d)


# ------------------------------------------------------------------------------------------- case transitions
def test_valid_case_transitions():
    c = _case()
    assert c.status == PENDING
    transition(c, NEEDS_INFO, "rev@x", "planner", "need site confirmation")
    transition(c, PENDING, "rev@x", "planner", "info received")
    transition(c, APPROVED, "rev@x", "planner", "", human_approved_qty=20)
    assert c.status == APPROVED and c.human_approved_qty == 20 and c.reviewer == "rev@x"


@pytest.mark.parametrize("terminal", [APPROVED, REJECTED])
def test_terminal_states_are_final(terminal):
    c = _case()
    transition(c, terminal, "rev@x", "planner", "done")
    with pytest.raises(InvalidTransition):
        transition(c, PENDING, "rev@x", "planner", "reopen")


def test_reject_requires_comment_and_role():
    with pytest.raises(InvalidTransition):
        transition(_case(), REJECTED, "rev@x", "planner", "")
    with pytest.raises(Unauthorized):
        transition(_case(), APPROVED, "someone@x", "viewer", "ok")


def test_approval_defaults_to_engine_quantity_and_never_touches_sap():
    c = transition(_case(), APPROVED, "rev@x", "planner", "")
    assert c.human_approved_qty == 15
    assert c.sap_action.startswith("NONE")


# ------------------------------------------------------------------------------------------- no unauthorized writes
def _py_files():
    return [p for d in ("src", "app") for p in (ROOT / d).rglob("*.py")]


def test_no_sap_or_external_write_clients():
    banned = re.compile(r"\b(pyrfc|sapnwrfc|requests\.(post|put|patch|delete)|urllib\.request|smtplib)\b", re.I)
    offenders = [str(p) for p in _py_files() if banned.search(p.read_text())]
    assert not offenders, offenders


def test_app_queries_are_read_only_and_gold_only():
    for key in QUERY_SPECS:
        sql = render_sql(key, f"{CATALOG}.gold")
        assert sql.lstrip().upper().startswith("SELECT")
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|GRANT)\b", sql, re.I)
        assert QUERY_SPECS[key][0] in APPROVED_GOLD_OBJECTS


def test_llm_output_cannot_set_quantities():
    src = (ROOT / "src" / "agents" / "workflow.py").read_text()
    tree = ast.parse(src)
    # recommended_qty on the case must come from the engine facts, never from the narrative dict
    assert 'recommended_qty=facts["recommended_qty"]' in src
    assert "narrative[\"recommended" not in src and "narrative.get(\"recommended" not in src
    assert tree is not None


# ------------------------------------------------------------------------------------------- shared definitions
def test_genie_app_dashboard_use_same_gold_views():
    genie = set(GENIE_TABLES)
    app = {v for v, _, _ in QUERY_SPECS.values()}
    dash_json = ROOT / "dashboards" / "rni_executive_inventory_intelligence.lvdash.json"
    dash_sql = " ".join(" ".join(d["queryLines"]) for d in json.loads(dash_json.read_text())["datasets"])
    dash = set(re.findall(rf"{CATALOG}\.gold\.(\w+)", dash_sql))
    for name, objs in [("genie", genie), ("app", app), ("dashboard", dash)]:
        assert objs <= set(APPROVED_GOLD_OBJECTS), (name, objs - set(APPROVED_GOLD_OBJECTS))
    assert not re.search(rf"{CATALOG}\.(silver|bronze|ml)\.", dash_sql)
    # the executive KPIs are read from the same table by all three consumers
    for consumer in (genie, app, dash):
        assert "inventory_value_metrics" in consumer or "kpi_executive" in consumer


def test_genie_space_config_well_formed():
    sp = serialized_space(CATALOG)
    ids = [t["identifier"] for t in sp["data_sources"]["tables"]]
    assert ids == sorted(ids) and all(".gold." in i for i in ids)
    assert len(sp["config"]["sample_questions"]) >= 7
    assert len(sp["instructions"]["example_question_sqls"]) >= 7
    for e in sp["instructions"]["example_question_sqls"]:
        objs = set(re.findall(rf"{CATALOG}\.gold\.(\w+)", e["sql"][0]))
        assert objs and objs <= set(GENIE_TABLES)


def test_live_app_kpis_equal_dashboard_kpis(spark):
    m = spark.table(f"{CATALOG}.gold.inventory_value_metrics").toPandas()
    k = spark.table(f"{CATALOG}.gold.kpi_executive").toPandas().iloc[0]
    assert abs(m.inventory_value.sum() - k.total_inventory_deployed_value) < 0.01
    assert abs(m.potential_excess_exposure_value.sum() - k.potential_excess_exposure_value) < 0.01
    assert abs(m.near_expiry_value.sum() - k.inventory_approaching_expiration_value) < 0.01


def test_live_genie_verified_sql_runs(spark):
    for q, sql in EXAMPLE_SQL:
        assert spark.sql(sql.format(g=f"{CATALOG}.gold")).count() > 0, q


# ------------------------------------------------------------------------------------------- E2E smoke (500 doses)
@pytest.fixture(scope="module")
def frame_repo(spark):
    from src.data.warehouse import FrameRepository
    frames = {v: spark.table(f"{CATALOG}.gold.{v}").toPandas() for v in APPROVED_GOLD_OBJECTS}
    return FrameRepository(frames, CATALOG)


def test_e2e_500_dose_request_flagged_evidenced_and_case_created(frame_repo, tmp_path, rules_cfg):
    from src.agents.workflow import InvestigationWorkflow
    from src.lakebase.store import SqliteCaseStore
    from src.optimization.engine import EngineRules
    q = frame_repo.query("review_queue")
    row = q[q.scenario_id == "SCN-01"].iloc[0]
    assert row.requested_qty == 500 and row.risk_category == "EXCESSIVE_REQUEST" and row.human_review_required
    store = SqliteCaseStore(str(tmp_path / "cases.db"))
    wf = InvestigationWorkflow(frame_repo, store, narrator=None, rules=EngineRules.from_config(rules_cfg))
    case = wf.create_case(row.customer_id, row.sku, row.order_line_id, "planner@demo", "planner")
    assert case.status == PENDING and case.recommended_qty == 15 and case.requested_qty == 500
    assert case.evidence["consumed_last_120d"] == 1 and case.evidence["on_hand_qty"] == 25
    assert case.evidence["par_only_baseline_qty"] == 35
    assert "DETERMINISTIC_FALLBACK" in case.summary_source          # labeled non-LLM when no endpoint
    with pytest.raises(Unauthorized):
        wf.create_case(row.customer_id, row.sku, row.order_line_id, "viewer@demo", "viewer")
    transition(case, APPROVED, "rev@demo", "planner", "approved 15 after site call")
    store.record_review(case, PENDING)
    back = store.get_case(case.case_id)
    assert back.status == APPROVED and back.human_approved_qty == 15 and back.sap_action.startswith("NONE")

"""App startup and key-screen rendering (Streamlit AppTest) against real Gold data in the Databricks test job."""
import sys

import pytest

from conftest import CATALOG, ROOT

st_testing = pytest.importorskip("streamlit.testing.v1")
APP_DIR = ROOT / "app"
for p in (str(ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="module")
def repo(spark):
    from src.data.warehouse import APPROVED_GOLD_OBJECTS, FrameRepository
    return FrameRepository({v: spark.table(f"{CATALOG}.gold.{v}").toPandas() for v in APPROVED_GOLD_OBJECTS}, CATALOG)


def _run(page, repo, tmp_path, **state):
    from src.lakebase.store import SqliteCaseStore
    at = st_testing.AppTest.from_file(str(APP_DIR / "pages" / page), default_timeout=120)
    at.session_state["_test_repo"] = repo
    at.session_state["_test_store"] = SqliteCaseStore(str(tmp_path / "cases.db"))
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_command_center_renders_with_500_dose_alert(repo, tmp_path):
    at = _run("command_center.py", repo, tmp_path)
    html = " ".join(m.value for m in at.markdown)
    assert "Total inventory deployed" in html and "Potentially excessive request" in html and "Desert Crest Medical Center" in html
    assert len(at.dataframe) >= 1


def test_shipment_advisor_reruns_engine_on_control_change(repo, tmp_path):
    at = _run("shipment_advisor.py", repo, tmp_path, advisor_pair=("CUST-001", "SKU-1001"))
    html = " ".join(m.value for m in at.markdown)
    assert "EXCESSIVE REQUEST" in html
    at.number_input(key="rqCUST-001-SKU-1001").set_value(15).run()
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "What-if (edited inputs)" in html and "EXCESSIVE REQUEST" not in html


def test_business_value_and_device_pages_render(repo, tmp_path):
    for page in ("business_value.py", "device_intelligence.py"):
        at = _run(page, repo, tmp_path)
        assert "Realized cash savings" in " ".join(m.value for m in at.markdown) or page != "business_value.py"


def test_cases_page_creates_case(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("RNI_DISABLE_LLM", "1")
    at = _run("operations_cases.py", repo, tmp_path)
    at.button[0].click().run()
    assert not at.exception
    assert any("created" in s.value for s in at.success)


def test_ask_page_renders_fallback_label(repo, tmp_path):
    at = _run("ask_rni_ai.py", repo, tmp_path)
    assert "curated SQL fallback" in " ".join(m.value for m in at.markdown).lower() or "genie" in " ".join(m.value for m in at.markdown).lower()

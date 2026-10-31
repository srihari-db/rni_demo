import datetime as dt
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LIVE = os.environ.get("RNI_LIVE") == "1"
CATALOG = os.environ.get("RNI_CATALOG", "rni_demo")


def _yaml(path):
    import yaml
    return yaml.safe_load(open(path))


@pytest.fixture(scope="session")
def cfg():
    return _yaml(ROOT / "config" / "demo_scenarios.yaml")


@pytest.fixture(scope="session")
def rules_cfg():
    return _yaml(ROOT / "config" / "business_rules.yaml")


@pytest.fixture(scope="session")
def snapshot(cfg):
    return dt.date.fromisoformat(str(cfg["simulation"]["snapshot_date"]))


@pytest.fixture(scope="session")
def spark():
    if not LIVE:
        pytest.skip("live Unity Catalog checks run only in the Databricks test task (RNI_LIVE=1)")
    from src.common.runtime import get_spark
    return get_spark()


@pytest.fixture(scope="session")
def tables(cfg):
    """Synthetic dataset: loaded from Unity Catalog silver tables when LIVE, else regenerated in-process."""
    if LIVE:
        from src.common.runtime import get_spark
        from scripts.load_rni_data import SILVER
        sp = get_spark()
        t = {n: sp.table(f"{CATALOG}.silver.{n}").toPandas() for n in SILVER}
        return t
    from src.data.simulator import simulate
    return simulate(cfg)

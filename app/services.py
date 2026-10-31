"""Cached service singletons and data loaders for the Streamlit app."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.workflow import InvestigationWorkflow, LLMNarrator  # noqa: E402
from src.data.warehouse import GoldRepository  # noqa: E402
from src.genie.client import GenieClient  # noqa: E402
from src.genie.fallback import CuratedFallback  # noqa: E402
from src.lakebase.store import get_store  # noqa: E402
from src.optimization.engine import EngineRules  # noqa: E402

log = logging.getLogger("rni.app")
logging.basicConfig(level=logging.INFO)


def _yaml(p):
    import yaml
    return yaml.safe_load(open(p))


@st.cache_resource
def rules() -> EngineRules:
    return EngineRules.from_config(_yaml(ROOT / "config" / "business_rules.yaml"))


@st.cache_resource
def repo():
    injected = st.session_state.get("_test_repo")
    return injected or GoldRepository()


def get_repo():
    return st.session_state.get("_test_repo") or repo()


@st.cache_resource
def genie() -> GenieClient:
    return GenieClient()


@st.cache_resource
def store():
    return get_store()


def get_store_cached():
    return st.session_state.get("_test_store") or store()


def workflow() -> InvestigationWorkflow:
    narrator = None if os.environ.get("RNI_DISABLE_LLM") == "1" else LLMNarrator()
    return InvestigationWorkflow(get_repo(), get_store_cached(), narrator=narrator, rules=rules())


@st.cache_data(ttl=600, show_spinner=False)
def _load(key: str, frozen_params: tuple = ()):
    return repo().query(key, dict(frozen_params) if frozen_params else None)


def load(key: str, **params) -> pd.DataFrame:
    test = st.session_state.get("_test_repo")
    if test is not None:
        return test.query(key, params or None)
    return _load(key, tuple(sorted(params.items())))


def current_user() -> str:
    try:
        h = st.context.headers
        return h.get("X-Forwarded-Email") or h.get("X-Forwarded-Preferred-Username") or "demo.planner@example.com"
    except Exception:
        return "demo.planner@example.com"


def current_role() -> str:
    # Demo: every signed-in app user acts as an RNI planner. In production map identity -> role via groups.
    return os.environ.get("RNI_DEFAULT_ROLE", "planner")


def safe(fn, fallback=None, message="This panel is temporarily unavailable."):
    """Run a loader; on failure show a friendly message (never raw internal errors to executives)."""
    try:
        return fn()
    except Exception as e:  # pragma: no cover - UI path
        log.exception("panel failure")
        st.info(message)
        return fallback

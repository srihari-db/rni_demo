"""RNI Intelligent Operations Command Center — Databricks App entry point (Streamlit)."""
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
APP = Path(__file__).resolve().parent
for p in (str(ROOT), str(APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

st.set_page_config(page_title="RNI Intelligent Operations Command Center", page_icon="🧊", layout="wide",
                   initial_sidebar_state="expanded")

import ui  # noqa: E402

ui.inject_css()

PAGES = [
    st.Page(str(APP / "pages" / "command_center.py"), title="Inventory Command Center", icon="📊", default=True),
    st.Page(str(APP / "pages" / "shipment_advisor.py"), title="Intelligent Shipment Advisor", icon="🧭"),
    st.Page(str(APP / "pages" / "ask_rni_ai.py"), title="Ask RNI AI", icon="💬"),
    st.Page(str(APP / "pages" / "business_value.py"), title="Business Value Simulator", icon="📈"),
    st.Page(str(APP / "pages" / "operations_cases.py"), title="AI Operations Cases", icon="🗂️"),
    st.Page(str(APP / "pages" / "device_intelligence.py"), title="Connected Device Intelligence", icon="📡"),
]

with st.sidebar:
    st.markdown("### RNI Command Center")
    st.caption("FFF Enterprises · Right Now Inventory")
nav = st.navigation(PAGES)
with st.sidebar:
    st.markdown("---")
    st.caption("Synthetic demonstration data · Decision support only · No SAP actions are triggered")
nav.run()

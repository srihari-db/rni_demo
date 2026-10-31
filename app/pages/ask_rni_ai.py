"""Screen 3 — Ask RNI AI: natural-language questions answered by the Genie agent on curated Gold views."""
import pandas as pd
import plotly.express as px
import streamlit as st

import services as svc
import ui
from src.genie.fallback import CuratedFallback
from src.genie.space_config import SAMPLE_QUESTIONS

ui.header("Ask RNI AI", "Natural-language questions answered by the RNI Inventory Intelligence Agent (Genie) on governed Gold data")

genie = svc.genie()
mode_live = genie.configured
st.markdown(ui.badge("Genie agent connected" if mode_live else "Genie not configured — curated SQL fallback", ui.TEAL if mode_live else ui.AMBER),
            unsafe_allow_html=True)

if "chat" not in st.session_state:
    st.session_state.chat = []
    st.session_state.conv_id = None

st.caption("Try a prevalidated question:")
cols = st.columns(4)
clicked = None
for i, q in enumerate(SAMPLE_QUESTIONS):
    if cols[i % 4].button(q, key=f"sq{i}", use_container_width=True):
        clicked = q


def auto_chart(df: pd.DataFrame):
    if df is None or df.empty or len(df) < 2 or len(df) > 40:
        return None
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cat = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    if not num or not cat:
        return None
    y = next((c for c in num if any(k in c for k in ("usd", "value", "rate", "ratio", "units", "qty"))), num[0])
    fig = px.bar(df, x=cat[0], y=y)
    fig.update_traces(marker_color=ui.NAVY)
    return ui.plotly_layout(fig, 300, legend=False)


def render(ans):
    src = ans.source
    if src == "GENIE":
        st.markdown(ui.badge("Live Genie response", ui.TEAL), unsafe_allow_html=True)
    elif src == "CURATED_SQL_FALLBACK":
        st.markdown(ui.badge("Curated SQL fallback — not a Genie response", ui.AMBER), unsafe_allow_html=True)
    else:
        st.markdown(ui.badge("Unavailable", ui.GREY), unsafe_allow_html=True)
    if ans.text:
        st.markdown(ans.text)
    if ans.error:
        st.info("The AI agent could not answer this right now. Try rephrasing or use a suggested question.")
    if ans.data is not None and len(ans.data):
        fig = auto_chart(ans.data)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(ans.data, hide_index=True, use_container_width=True)
    if ans.sql:
        with st.expander("SQL used"):
            st.code(ans.sql, language="sql")
    if ans.suggested_questions:
        st.caption("Follow-ups: " + " · ".join(ans.suggested_questions))


for turn in st.session_state.chat:
    with st.chat_message("user"):
        st.markdown(turn["q"])
    with st.chat_message("assistant", avatar="🧊"):
        render(turn["a"])

q = st.chat_input("Ask about inventory, returns, expiration risk, forecasts or flagged requests…") or clicked
if q:
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant", avatar="🧊"):
        with st.spinner("Thinking…"):
            ans = genie.ask(q, st.session_state.conv_id) if mode_live else None
            if ans is None or ans.source == "ERROR":
                fb = CuratedFallback(svc.get_repo())
                try:
                    fb_ans = fb.answer(q)
                    if ans is not None and ans.source == "ERROR":
                        fb_ans.text = "Genie was unavailable for this question. " + (fb_ans.text or "")
                    ans = fb_ans
                except Exception:
                    from src.genie.client import GenieAnswer
                    ans = GenieAnswer(q, "ERROR", error="unavailable")
            if ans.source == "GENIE":
                st.session_state.conv_id = ans.conversation_id
        render(ans)
    st.session_state.chat.append({"q": q, "a": ans})

if st.session_state.chat and st.button("New conversation"):
    st.session_state.chat, st.session_state.conv_id = [], None
    st.rerun()
ui.footnote("Genie answers are generated from the approved Gold views only. Curated fallback answers are fixed, "
            "verified SQL queries and are labeled as such. All data synthetic.")

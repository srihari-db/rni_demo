"""Shared visual components for the RNI Command Center (enterprise SaaS styling)."""
from __future__ import annotations

import html
from typing import Optional

import streamlit as st

NAVY = "#0B2545"
NAVY_2 = "#13315C"
TEAL = "#0FA3A3"
TEAL_LIGHT = "#E6F6F6"
AMBER = "#F2A541"
RED = "#D64545"
GREY = "#5B6573"
LIGHT = "#F5F7FA"
BORDER = "#E3E8EF"
SERIES = [NAVY, TEAL, AMBER, "#7A8CA5", RED, "#4C9F70", "#9B6FB0"]
RISK_COLORS = {"EXCESSIVE_REQUEST": RED, "STOCKOUT_RISK": AMBER, "EXPIRY_RISK": "#E07B39",
               "CRITICAL_POLICY_HOLD": "#9B6FB0", "WITHIN_POLICY": TEAL, "MISSING_DATA": GREY}

CSS = f"""
<style>
  .stApp {{ background: #FFFFFF; }}
  section[data-testid="stSidebar"] {{ background: {NAVY}; }}
  section[data-testid="stSidebar"] * {{ color: #E8EEF6 !important; }}
  section[data-testid="stSidebar"] a[aria-current="page"] {{ background: {NAVY_2}; border-left: 3px solid {TEAL}; }}
  .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px; }}
  h1, h2, h3, h4 {{ color: {NAVY}; font-family: 'Inter', 'Segoe UI', sans-serif; }}
  .rni-header {{ background: linear-gradient(90deg, {NAVY} 0%, {NAVY_2} 100%); color: white; border-radius: 12px;
                 padding: 18px 24px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }}
  .rni-header h1 {{ color: white; font-size: 1.55rem; margin: 0; }}
  .rni-header p {{ color: #C9D6E8; margin: 4px 0 0 0; font-size: 0.92rem; }}
  .rni-pill {{ background: rgba(255,255,255,0.12); color: #fff; border-radius: 999px; padding: 4px 12px; font-size: 0.78rem; }}
  .kpi {{ background: white; border: 1px solid {BORDER}; border-radius: 12px; padding: 14px 16px; height: 100%;
          box-shadow: 0 1px 2px rgba(16,24,40,0.04); border-top: 4px solid {NAVY}; }}
  .kpi .label {{ color: {GREY}; font-size: 0.78rem; text-transform: uppercase; letter-spacing: .04em; }}
  .kpi .value {{ color: {NAVY}; font-size: 1.6rem; font-weight: 700; margin-top: 4px; }}
  .kpi .sub {{ color: {GREY}; font-size: 0.78rem; margin-top: 2px; }}
  .kpi.teal {{ border-top-color: {TEAL}; }} .kpi.amber {{ border-top-color: {AMBER}; }} .kpi.red {{ border-top-color: {RED}; }}
  .alert {{ border-radius: 10px; padding: 12px 16px; margin: 8px 0 14px 0; border: 1px solid; }}
  .alert.red {{ background: #FDECEC; border-color: #F4C2C2; color: #7A1F1F; }}
  .alert.amber {{ background: #FFF6E8; border-color: #F7D9A6; color: #7A4A08; }}
  .alert.teal {{ background: {TEAL_LIGHT}; border-color: #B5E3E3; color: #0B5555; }}
  .alert.grey {{ background: {LIGHT}; border-color: {BORDER}; color: {GREY}; }}
  .badge {{ display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 0.74rem; font-weight: 600;
            color: white; margin-right: 6px; }}
  .chip {{ display: inline-block; border-radius: 6px; padding: 2px 8px; font-size: 0.74rem; background: {LIGHT};
           border: 1px solid {BORDER}; color: {NAVY}; margin: 2px 4px 2px 0; }}
  .section {{ color: {NAVY}; font-weight: 700; font-size: 1.05rem; margin: 18px 0 6px 0; }}
  .muted {{ color: {GREY}; font-size: 0.82rem; }}
  .footnote {{ color: {GREY}; font-size: 0.75rem; margin-top: 18px; border-top: 1px solid {BORDER}; padding-top: 8px; }}
  div[data-testid="stMetricValue"] {{ color: {NAVY}; }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str, pill: Optional[str] = "Synthetic demo data"):
    pill_html = f'<span class="rni-pill">{html.escape(pill)}</span>' if pill else ""
    st.markdown(f'<div class="rni-header"><div><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>'
                f'{pill_html}</div>', unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str = "", tone: str = ""):
    st.markdown(f'<div class="kpi {tone}"><div class="label">{html.escape(label)}</div>'
                f'<div class="value">{html.escape(value)}</div><div class="sub">{html.escape(sub)}</div></div>',
                unsafe_allow_html=True)


def alert(text_html: str, tone: str = "amber"):
    st.markdown(f'<div class="alert {tone}">{text_html}</div>', unsafe_allow_html=True)


def badge(text: str, color: str) -> str:
    return f'<span class="badge" style="background:{color}">{html.escape(text)}</span>'


def chips(items) -> str:
    return "".join(f'<span class="chip">{html.escape(str(i))}</span>' for i in items)


def section(title: str):
    st.markdown(f'<div class="section">{html.escape(title)}</div>', unsafe_allow_html=True)


def footnote(text: str = "All customers, products, quantities and dollar values are synthetic and illustrative. "
                         "Recommendations are decision support, not clinical guidance."):
    st.markdown(f'<div class="footnote">{html.escape(text)}</div>', unsafe_allow_html=True)


def usd(v, digits: int = 0) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 1e6:
        return f"${v / 1e6:,.2f}M"
    if abs(v) >= 1e4:
        return f"${v / 1e3:,.0f}K"
    return f"${v:,.{digits}f}"


def num(v) -> str:
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def plotly_layout(fig, height: int = 330, legend: bool = True):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=36, b=10), paper_bgcolor="white", plot_bgcolor="white",
                      font=dict(family="Inter, Segoe UI, sans-serif", color=NAVY, size=12), colorway=SERIES,
                      showlegend=legend, legend=dict(orientation="h", y=-0.18, x=0),
                      title_font=dict(size=14, color=NAVY))
    fig.update_xaxes(showgrid=False, linecolor=BORDER)
    fig.update_yaxes(gridcolor="#EEF1F5", zerolinecolor=BORDER)
    return fig

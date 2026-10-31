"""Bounded AI-assisted investigation workflow.

    authorized request -> structured fact tools (fixed Gold queries) -> deterministic engine rerun
    -> LLM narrative (or deterministic fallback) -> missing info / policy constraints -> proposed human action
    -> case saved (pending review)

Guardrails
* The LLM receives a JSON fact sheet and returns narrative JSON only. It cannot run SQL, call tools, change
  quantities or write anywhere. ``recommended_qty`` always comes from the decision engine.
* Any number the LLM proposes as a quantity is ignored; the case stores engine and human quantities only.
* There is no SAP (or any external write) client in this package.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable, Dict, Optional

from ..optimization.batch import input_from_json
from ..optimization.engine import EngineRules, recommend
from .cases import REVIEWER_ROLES, InvestigationCase, Unauthorized

log = logging.getLogger("rni.agent")

SYSTEM_PROMPT = """You are an RNI inventory operations analyst assistant at a pharmaceutical distributor.
You receive a JSON fact sheet about one flagged shipment request. All data is synthetic demo data.
Write for a planner. Rules:
- Use ONLY the facts provided. Do not invent numbers.
- Do NOT propose or change any quantity. The deterministic engine's recommended_qty is authoritative; a human decides.
- Do not give clinical or dosing advice. Emergency/critical stock follows approved policy.
- Describe potential exposure as "potential", never as savings.
Return strict JSON with keys: summary (<=90 words), risk_explanation (<=70 words),
missing_information (list of short strings), proposed_next_action (<=40 words, a human-review action)."""


class FactTools:
    """Structured, read-only data tools. Each maps to a fixed, parameterized Gold query."""

    def __init__(self, repo):
        self.repo = repo

    def recommendation(self, customer_id: str, sku: str, order_line_id: Optional[str]) -> dict:
        recs = self.repo.query("pair_recs", {"customer_id": customer_id, "sku": sku})
        if order_line_id:
            r = recs[recs.order_line_id == order_line_id]
        else:
            r = recs[recs.recommendation_type == "CYCLE_REVIEW"]
        return {} if r.empty else r.iloc[0].to_dict()

    def returns_history(self, customer_id: str, sku: str) -> dict:
        r = self.repo.query("pair_returns", {"customer_id": customer_id, "sku": sku})
        r12 = r[r.in_last_12_months] if len(r) else r
        return dict(returns_12m=int(len(r12)), returned_units_12m=int(r12.returned_qty.sum()) if len(r12) else 0,
                    return_logistics_cost_12m=round(float(r12.return_logistics_cost.sum()), 2) if len(r12) else 0.0)

    def lots(self, customer_id: str, sku: str) -> list:
        l = self.repo.query("pair_lots", {"customer_id": customer_id, "sku": sku})
        return [dict(lot_id=x.lot_id, qty=int(x.on_hand_qty), expiry_date=str(x.expiry_date),
                     days_to_expiry=int(x.days_to_expiry)) for x in l.itertuples()]


def _deterministic_narrative(f: dict) -> dict:
    rq, rc = f.get("requested_qty"), f.get("recommended_qty")
    s = (f"{f['customer_name']} requested {rq} units of {f['product_name']}. The site holds {f['on_hand_qty']} "
         f"(PAR {f['par_level']}, mandatory minimum {f['mandatory_minimum']}) and consumed {f['consumed_last_120d']:.0f} "
         f"in the last 120 days; 30-day forecast demand is {f['forecast_30d_qty']:.1f}. The decision engine recommends "
         f"{rc} units.")
    risk = (f"Risk category {f['risk_category']}: {f['review_reason']} Potential exposure "
            f"${f['potential_exposure_value']:,.0f} (not realized savings).")
    missing = ["Confirmation of any planned clinical/program changes at the site that could raise demand",
               "Reason the site gave for the requested quantity"]
    action = "Planner to contact the site, confirm demand drivers, then approve, modify or reject the request."
    return dict(summary=s, risk_explanation=risk, missing_information=missing, proposed_next_action=action)


class LLMNarrator:
    def __init__(self, endpoint: Optional[str] = None, workspace_client=None):
        self.endpoint = endpoint or os.environ.get("SERVING_ENDPOINT_NAME")
        self._w = workspace_client

    def __call__(self, facts: dict) -> Optional[dict]:
        if not self.endpoint:
            return None
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
        w = self._w or WorkspaceClient()
        resp = w.serving_endpoints.query(
            name=self.endpoint, max_tokens=600, temperature=0.0,
            messages=[ChatMessage(role=ChatMessageRole.SYSTEM, content=SYSTEM_PROMPT),
                      ChatMessage(role=ChatMessageRole.USER, content=json.dumps(facts, default=str))])
        text = resp.choices[0].message.content
        if isinstance(text, list):
            text = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in text)
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0) if m else text)
        out = {k: data.get(k) for k in ("summary", "risk_explanation", "missing_information", "proposed_next_action")}
        if not out["summary"] or not out["proposed_next_action"]:
            raise ValueError("incomplete LLM narrative")
        if not isinstance(out["missing_information"], list):
            out["missing_information"] = [str(out["missing_information"])]
        return out


class InvestigationWorkflow:
    def __init__(self, repo, store, narrator: Optional[Callable[[dict], Optional[dict]]] = None,
                 rules: Optional[EngineRules] = None):
        self.tools = FactTools(repo)
        self.store = store
        self.narrator = narrator
        self.rules = rules or EngineRules()

    def build_facts(self, customer_id: str, sku: str, order_line_id: Optional[str]) -> Dict:
        rec = self.tools.recommendation(customer_id, sku, order_line_id)
        if not rec:
            raise ValueError("no recommendation found for this customer/SKU")
        inp = input_from_json(rec["engine_input"])
        engine = recommend(inp, self.rules)               # authoritative quantity recomputed, not trusted from text
        if engine.recommended_qty != (None if rec["recommended_qty"] is None else int(rec["recommended_qty"])):
            log.warning("stored recommendation differs from engine rerun for %s/%s", customer_id, sku)
        facts = dict(
            customer_id=customer_id, customer_name=rec["customer_name"], sku=sku, product_name=rec["product_name"],
            order_line_id=order_line_id, recommendation_id=rec["recommendation_id"],
            requested_qty=engine.requested_qty, recommended_qty=engine.recommended_qty,
            par_only_baseline_qty=engine.par_only_baseline_qty, on_hand_qty=inp.on_hand_qty,
            par_level=inp.par_level, mandatory_minimum=inp.mandatory_minimum,
            consumed_last_120d=float(inp.consumption_last_120d or 0), forecast_30d_qty=float(inp.forecast_qty_30d or 0),
            forecast_30d_upper=float(inp.forecast_upper_30d or 0), critical_stock_flag=inp.critical_stock_flag,
            risk_category=engine.risk_category, risk_factors=engine.risk_factors,
            policy_constraints=engine.policy_constraints, review_reason=engine.review_reason,
            potential_exposure_value=engine.potential_exposure_value, engine_explanation=engine.explanation,
            human_review_required=engine.human_review_required,
            returns=self.tools.returns_history(customer_id, sku), lots=self.tools.lots(customer_id, sku),
            engine_version=engine.engine_version, data_basis="SYNTHETIC DEMO DATA",
        )
        return facts

    def create_case(self, customer_id: str, sku: str, order_line_id: Optional[str], requested_by: str,
                    role: str) -> InvestigationCase:
        if role not in REVIEWER_ROLES:
            raise Unauthorized(f"role '{role}' may not open investigation cases")
        facts = self.build_facts(customer_id, sku, order_line_id)
        narrative, source = None, "DETERMINISTIC_FALLBACK (non-LLM)"
        if self.narrator is not None:
            try:
                narrative = self.narrator(facts)
                if narrative:
                    source = f"LLM:{getattr(self.narrator, 'endpoint', 'model')}"
            except Exception as e:
                log.warning("LLM narrative unavailable, using deterministic summary: %s", e)
                narrative = None
        if not narrative:
            narrative = _deterministic_narrative(facts)
        missing = list(narrative.get("missing_information") or [])
        if facts["critical_stock_flag"]:
            missing.append("Confirm site emergency-preparedness requirements before any reduction (critical product)")
        case = InvestigationCase(
            customer_id=customer_id, customer_name=facts["customer_name"], sku=sku, product_name=facts["product_name"],
            requested_qty=facts["requested_qty"], recommended_qty=facts["recommended_qty"],
            risk_category=facts["risk_category"], evidence=facts, ai_summary=narrative["summary"],
            risk_explanation=narrative["risk_explanation"], proposed_next_action=narrative["proposed_next_action"],
            missing_information=missing, summary_source=source, created_by=requested_by,
            order_line_id=order_line_id, recommendation_id=facts["recommendation_id"])
        self.store.save_case(case)
        self.store.log_activity(case.case_id, "CASE_CREATED", requested_by,
                                {"summary_source": source, "tools": ["recommendation", "returns_history", "lots", "engine"]})
        return case

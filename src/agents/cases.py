"""Investigation case model and status workflow. Pure Python (no I/O)."""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict, dataclass, field
from typing import List, Optional

PENDING, APPROVED, REJECTED, NEEDS_INFO = "PENDING_REVIEW", "APPROVED", "REJECTED", "NEEDS_MORE_INFO"
STATUSES = (PENDING, APPROVED, REJECTED, NEEDS_INFO)
TRANSITIONS = {
    PENDING: {APPROVED, REJECTED, NEEDS_INFO},
    NEEDS_INFO: {PENDING, APPROVED, REJECTED},
    APPROVED: set(),          # terminal
    REJECTED: set(),          # terminal
}
REVIEWER_ROLES = {"planner", "inventory_manager", "admin"}


class InvalidTransition(ValueError):
    pass


class Unauthorized(PermissionError):
    pass


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


@dataclass
class InvestigationCase:
    customer_id: str
    customer_name: str
    sku: str
    product_name: str
    requested_qty: Optional[int]
    recommended_qty: Optional[int]
    risk_category: str
    evidence: dict
    ai_summary: str
    risk_explanation: str
    proposed_next_action: str
    missing_information: List[str]
    summary_source: str                    # LLM:<endpoint> | DETERMINISTIC_FALLBACK
    created_by: str
    order_line_id: Optional[str] = None
    recommendation_id: Optional[str] = None
    status: str = PENDING
    reviewer: Optional[str] = None
    reviewer_comments: Optional[str] = None
    human_approved_qty: Optional[int] = None
    case_id: str = field(default_factory=lambda: "CASE-" + uuid.uuid4().hex[:10].upper())
    created_at: dt.datetime = field(default_factory=now)
    updated_at: dt.datetime = field(default_factory=now)
    # explicit statement that nothing downstream is triggered
    sap_action: str = "NONE — decision support only; no SAP shipment or return is created"

    def to_dict(self):
        return asdict(self)


def transition(case: InvestigationCase, new_status: str, reviewer: str, role: str, comments: str = "",
               human_approved_qty: Optional[int] = None) -> InvestigationCase:
    if role not in REVIEWER_ROLES:
        raise Unauthorized(f"role '{role}' may not review cases")
    if new_status not in STATUSES:
        raise InvalidTransition(f"unknown status {new_status}")
    if new_status not in TRANSITIONS[case.status]:
        raise InvalidTransition(f"{case.status} -> {new_status} is not allowed")
    if new_status == APPROVED and human_approved_qty is None:
        human_approved_qty = case.recommended_qty
    if human_approved_qty is not None and human_approved_qty < 0:
        raise InvalidTransition("approved quantity cannot be negative")
    if new_status in (REJECTED, NEEDS_INFO) and not comments.strip():
        raise InvalidTransition("a comment is required to reject or request more information")
    case.status = new_status
    case.reviewer = reviewer
    case.reviewer_comments = comments
    if new_status == APPROVED:
        case.human_approved_qty = int(human_approved_qty) if human_approved_qty is not None else None
    case.updated_at = now()
    return case

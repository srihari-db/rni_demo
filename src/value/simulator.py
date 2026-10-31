"""Business value simulator — ILLUSTRATIVE ONLY.

Keeps three things strictly separate (never added together):
  1. Inventory value released      — one-time working-capital effect (balance sheet), not annual savings
  2. Potential annual cost avoidance — returns logistics, expiry losses, carrying cost, availability margin
  3. Realized cash savings          — NOT claimed: requires validation against FFF operational/finance data

Double counting is avoided by construction:
  * returns logistics avoided counts only logistics/processing COST of avoidable returns, never product value
  * expiry losses avoided are based on HISTORICAL expired value (already written off), which is disjoint from the
    CURRENT excess on hand used for inventory released
  * carrying cost is charged only on the released portion of current excess inventory
  * availability benefit is margin on unmet demand (stockouts), unrelated to the inventory buckets above
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ValueBaseline:
    """Facts derived from Gold tables (12 months unless stated)."""
    excess_on_hand_value: float           # current, above PAR, not near expiry (mutually exclusive bucket)
    near_expiry_value: float              # current, expiring <= 90 days
    expired_value_12m: float              # historical expiry disposals
    avoidable_returns_count_12m: int      # returns driven by over-allocation
    avoidable_return_logistics_12m: float
    unmet_units_12m: float                # stockout demand not met
    avg_margin_per_unit: float            # selling price - cost, weighted


@dataclass
class ValueAssumptions:
    cost_per_returned_shipment: float = 450.0     # cold-chain shipping + QA processing per avoidable return
    expiry_loss_rate: float = 0.60                # share of expired value that is an unrecoverable loss
    avoidable_excess_pct: float = 0.35            # share of excess allocation considered avoidable
    expiry_reduction_pct: float = 0.30            # share of expiry losses avoidable with earlier signals
    carrying_cost_rate: float = 0.12              # annual carrying cost on inventory value
    availability_improvement_pct: float = 0.25    # share of unmet demand recovered
    annual_solution_cost: float = 250000.0


@dataclass
class ValueResult:
    inventory_value_released: float
    returns_logistics_avoided: float
    expiry_losses_avoided: float
    carrying_cost_avoided: float
    availability_margin_protected: float
    total_annual_cost_avoidance: float
    annual_solution_cost: float
    net_annual_benefit: float
    benefit_to_cost_ratio: float
    realized_cash_savings: None = None
    label: str = "ILLUSTRATIVE — synthetic data; not validated FFF financials"

    def to_dict(self):
        return asdict(self)


def simulate(base: ValueBaseline, a: ValueAssumptions) -> ValueResult:
    pct = max(0.0, min(1.0, a.avoidable_excess_pct))
    released = base.excess_on_hand_value * pct
    returns_avoided = base.avoidable_returns_count_12m * pct * a.cost_per_returned_shipment
    expiry_avoided = base.expired_value_12m * a.expiry_loss_rate * max(0.0, min(1.0, a.expiry_reduction_pct))
    carrying = released * a.carrying_cost_rate
    availability = base.unmet_units_12m * max(0.0, min(1.0, a.availability_improvement_pct)) * base.avg_margin_per_unit
    total = returns_avoided + expiry_avoided + carrying + availability
    net = total - a.annual_solution_cost
    bcr = total / a.annual_solution_cost if a.annual_solution_cost > 0 else float("inf")
    return ValueResult(round(released, 2), round(returns_avoided, 2), round(expiry_avoided, 2), round(carrying, 2),
                       round(availability, 2), round(total, 2), round(a.annual_solution_cost, 2), round(net, 2),
                       round(bcr, 3))

"""Data-quality and reconciliation checks for the synthetic RNI dataset.

Each check takes a ``{table_name: DataFrame}`` mapping and returns a list of ``CheckResult``. The same functions
run inside the generator (fail fast), in ``tests/test_data_integrity.py`` and against the loaded Unity Catalog
tables in the Databricks test job.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

ORDER_STATES = {"PENDING_REVIEW", "APPROVED", "IN_TRANSIT", "DELIVERED", "PARTIALLY_DELIVERED", "REJECTED", "CANCELLED"}
EVENT_TYPES = {"OPENING_BALANCE", "RECEIPT", "CONSUMPTION", "RETURN", "EXPIRY_DISPOSAL"}
TRANSACTION_TABLES = ["usage_history", "stockout_events", "shipment_orders", "return_orders", "inventory_events",
                      "inventory_positions", "par_levels"]


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    failures: int = 0

    def as_dict(self):
        return dict(name=self.name, passed=bool(self.passed), detail=self.detail, failures=int(self.failures))


def _res(name, bad: pd.DataFrame, detail_ok="", sample_cols=None) -> CheckResult:
    n = int(len(bad))
    if n == 0:
        return CheckResult(name, True, detail_ok)
    sample = bad.head(3)[sample_cols] if sample_cols else bad.head(3)
    return CheckResult(name, False, f"{n} violating rows, e.g. {sample.to_dict('records')}", n)


def _to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.date


# ------------------------------------------------------------------------------------------------- referential
def check_referential_integrity(t: Dict[str, pd.DataFrame]) -> List[CheckResult]:
    out = []
    custs, skus = set(t["customer_master"].customer_id), set(t["product_master"].sku)
    pairs = set(map(tuple, t["customer_product_assignments"][["customer_id", "sku"]].values))
    devices = t["rni_devices"].set_index("device_id")["customer_id"].to_dict()
    lots = t["lot_master"].set_index("lot_id")["sku"].to_dict()
    for name in TRANSACTION_TABLES:
        df = t[name]
        if df.empty:
            continue
        bad = df[~df.customer_id.isin(custs) | ~df.sku.isin(skus)]
        out.append(_res(f"ri_customer_sku[{name}]", bad, f"{len(df):,} rows reference valid customer and SKU"))
        bad = df[[(c, s) not in pairs for c, s in zip(df.customer_id, df.sku)]]
        out.append(_res(f"ri_assignment[{name}]", bad, "every customer/SKU pair is an active RNI assignment"))
    for name in ["inventory_events", "inventory_positions", "return_orders", "usage_history"]:
        df = t[name]
        bad = df[[devices.get(d) != c for d, c in zip(df.device_id, df.customer_id)]]
        out.append(_res(f"ri_device[{name}]", bad, "device belongs to the transacting customer"))
    for name in ["inventory_events", "inventory_positions", "return_orders"]:
        df = t[name]
        bad = df[[lots.get(l) != s for l, s in zip(df.lot_id, df.sku)]]
        out.append(_res(f"ri_lot[{name}]", bad, "lot exists and belongs to the SKU"))
    al = t["shipment_lot_allocations"]
    lines = set(t["shipment_orders"].order_line_id)
    out.append(_res("ri_allocation_order_line", al[~al.order_line_id.isin(lines)], "allocations reference order lines"))
    rl = t["return_order_links"]
    out.append(_res("ri_return_links", rl[~rl.order_line_id.isin(lines) | ~rl.return_id.isin(set(t["return_orders"].return_id))],
                    "return links reference real returns and order lines"))
    for name, col in [("customer_master", "customer_id"), ("product_master", "sku"), ("rni_devices", "device_id"),
                      ("lot_master", "lot_id"), ("shipment_orders", "order_line_id"), ("return_orders", "return_id"),
                      ("inventory_events", "event_id")]:
        df = t[name]
        out.append(_res(f"unique_id[{name}.{col}]", df[df[col].duplicated(keep=False)], "identifier is unique"))
    return out


# ------------------------------------------------------------------------------------------------- inventory
def check_inventory(t: Dict[str, pd.DataFrame]) -> List[CheckResult]:
    out = []
    ev, pos = t["inventory_events"], t["inventory_positions"]
    out.append(_res("no_negative_inventory[positions]", pos[pos.on_hand_qty < 0], "all on-hand quantities >= 0"))
    out.append(_res("no_negative_inventory[ledger]", ev[ev.lot_balance_after < 0], "running lot balances never negative"))
    out.append(_res("valid_event_types", ev[~ev.event_type.isin(EVENT_TYPES)], "event types valid"))
    sign_bad = ev[((ev.event_type.isin(["OPENING_BALANCE", "RECEIPT"])) & (ev.quantity_delta <= 0)) |
                  ((ev.event_type.isin(["CONSUMPTION", "RETURN", "EXPIRY_DISPOSAL"])) & (ev.quantity_delta >= 0))]
    out.append(_res("event_sign_convention", sign_bad, "receipts positive, depletions negative"))

    # chronological ledger
    evs = ev.sort_values("event_seq")
    d = pd.to_datetime(evs.event_date)
    out.append(_res("ledger_chronological", evs[d.diff().dt.days.fillna(0) < 0], "event sequence is chronological"))

    # opening + receipts - consumption - returns - disposal == closing (per customer/SKU/lot, current snapshot)
    cur = pos[pos.is_current] if "is_current" in pos else pos[pos.snapshot_date == pos.snapshot_date.max()]
    piv = ev.pivot_table(index=["customer_id", "sku", "lot_id"], columns="event_type", values="quantity_delta",
                         aggfunc="sum", fill_value=0)
    for c in EVENT_TYPES:
        if c not in piv:
            piv[c] = 0
    piv["closing_from_ledger"] = (piv.OPENING_BALANCE + piv.RECEIPT + piv.CONSUMPTION + piv.RETURN + piv.EXPIRY_DISPOSAL)
    merged = piv.reset_index().merge(cur[["customer_id", "sku", "lot_id", "on_hand_qty"]], how="outer",
                                     on=["customer_id", "sku", "lot_id"]).fillna({"on_hand_qty": 0, "closing_from_ledger": 0})
    bad = merged[merged.closing_from_ledger != merged.on_hand_qty]
    out.append(_res("ledger_reconciles_to_current_snapshot", bad,
                    f"{len(merged):,} customer/SKU/lot balances: opening + receipts - consumption - returns - disposal = closing"))

    # every month-end snapshot reconciles to the cumulative ledger at that date
    ev2 = ev.assign(event_date=_to_date(ev.event_date))
    snaps = sorted(set(_to_date(pos.snapshot_date)))
    mism = 0
    for sd in snaps:
        led = ev2[ev2.event_date <= sd].groupby(["customer_id", "sku", "lot_id"]).quantity_delta.sum()
        led = led[led != 0]
        sp = pos[_to_date(pos.snapshot_date) == sd].set_index(["customer_id", "sku", "lot_id"]).on_hand_qty
        mism += int((led.sub(sp, fill_value=0) != 0).sum())
    out.append(CheckResult("ledger_reconciles_to_all_snapshots", mism == 0,
                           f"{len(snaps)} snapshot dates reconciled" if mism == 0 else f"{mism} lot balances differ", mism))

    # utilization vs movement consistency
    use = t["usage_history"].groupby(["customer_id", "sku"]).quantity_consumed.sum()
    cons = -ev[ev.event_type == "CONSUMPTION"].groupby(["customer_id", "sku"]).quantity_delta.sum()
    diff = use.sub(cons, fill_value=0)
    out.append(CheckResult("usage_matches_consumption_events", bool((diff == 0).all()),
                           "usage_history equals CONSUMPTION ledger events", int((diff != 0).sum())))
    so = t["shipment_orders"]
    delivered = so[so.order_status.isin(["DELIVERED", "PARTIALLY_DELIVERED"])]
    rec = ev[ev.event_type == "RECEIPT"].groupby("reference_id").quantity_delta.sum()
    shp = delivered.set_index("order_line_id").shipped_qty
    diff = shp.sub(rec, fill_value=0)
    out.append(CheckResult("receipts_match_delivered_shipments", bool((diff == 0).all()),
                           "RECEIPT events equal shipped qty of delivered order lines", int((diff != 0).sum())))
    ret_ev = -ev[ev.event_type == "RETURN"].groupby("reference_id").quantity_delta.sum()
    diff = t["return_orders"].set_index("return_id").returned_qty.sub(ret_ev, fill_value=0)
    out.append(CheckResult("returns_match_return_events", bool((diff == 0).all()),
                           "return_orders equal RETURN ledger events", int((diff != 0).sum())))
    return out


# ------------------------------------------------------------------------------------------------- returns
def check_returns(t: Dict[str, pd.DataFrame]) -> List[CheckResult]:
    out = []
    ev, ro = t["inventory_events"], t["return_orders"]
    rev = ev[ev.event_type == "RETURN"][["reference_id", "lot_balance_after", "quantity_delta"]]
    j = ro.merge(rev, left_on="return_id", right_on="reference_id", how="left")
    j["available_before"] = j.lot_balance_after - j.quantity_delta
    out.append(_res("returns_within_available_inventory", j[j.returned_qty > j.available_before],
                    f"{len(ro):,} returns never exceed the lot quantity on hand", ["return_id", "returned_qty", "available_before"]))
    exp = j[_to_date(j.lot_expiry_date) <= _to_date(j.return_date)]
    out.append(_res("returns_only_unexpired_lots", exp, "no expired product is returned"))
    out.append(_res("return_cost_positive", ro[(ro.return_shipping_cost <= 0) | (ro.returned_qty <= 0)],
                    "return quantities and cold-chain costs positive"))
    # returned lot must have been on hand at that customer before the return (from receipts or opening stock)
    first_in = ev[ev.event_type.isin(["OPENING_BALANCE", "RECEIPT"])].groupby(["customer_id", "lot_id"]).event_date.min()
    jj = ro.join(first_in.rename("first_in"), on=["customer_id", "lot_id"])
    out.append(_res("returns_from_historical_inventory", jj[jj.first_in.isna() | (_to_date(jj.first_in) > _to_date(jj.return_date))],
                    "every returned lot was previously received by that customer"))
    return out


# ------------------------------------------------------------------------------------------------- orders
def check_order_lifecycle(t: Dict[str, pd.DataFrame], snapshot: dt.date) -> List[CheckResult]:
    so = t["shipment_orders"].copy()
    out = [_res("order_status_valid", so[~so.order_status.isin(ORDER_STATES)], "all order statuses valid")]
    rq, sh, dl = _to_date(so.request_date), pd.to_datetime(so.shipment_date).dt.date, pd.to_datetime(so.delivered_date).dt.date
    st = so.order_status
    bad = so[
        (st.isin(["DELIVERED", "PARTIALLY_DELIVERED"]) & (so.shipment_date.isna() | so.delivered_date.isna() | (so.shipped_qty <= 0)))
        | (st.isin(["DELIVERED", "PARTIALLY_DELIVERED", "IN_TRANSIT"]) & so.shipment_date.notna() & (sh <= rq))
        | (st.isin(["DELIVERED", "PARTIALLY_DELIVERED"]) & (dl < sh))
        | ((st == "DELIVERED") & (so.shipped_qty != so.approved_qty))
        | ((st == "PARTIALLY_DELIVERED") & (so.shipped_qty >= so.approved_qty))
        | (st.isin(["REJECTED", "CANCELLED", "PENDING_REVIEW", "APPROVED"]) & ((so.shipped_qty != 0) | so.shipment_date.notna()))
        | ((st == "IN_TRANSIT") & (so.shipment_date.isna() | so.delivered_date.notna()))
        | ((st == "PENDING_REVIEW") & so.approved_qty.notna())
        | (st.isin(["DELIVERED", "PARTIALLY_DELIVERED", "IN_TRANSIT"]) & (so.shipped_qty > so.approved_qty))
        | (so.approved_qty.notna() & (so.approved_qty > so.requested_qty))
        | (rq > snapshot)
    ]
    out.append(_res("order_lifecycle_consistent", bad, f"{len(so):,} order lines have consistent lifecycle dates/quantities",
                    ["order_line_id", "order_status"]))
    pend = so[st == "PENDING_REVIEW"]
    out.append(_res("pending_requests_are_recent", pend[(snapshot - _to_date(pend.request_date)).apply(lambda x: x.days) > 7],
                    f"{len(pend)} pending requests raised within the last week"))
    al = t["shipment_lot_allocations"].groupby("order_line_id").allocated_qty.sum()
    shipped = so[so.shipped_qty > 0].set_index("order_line_id").shipped_qty
    diff = shipped.sub(al, fill_value=0)
    out.append(CheckResult("lot_allocations_match_shipped_qty", bool((diff == 0).all()),
                           "lot allocations sum to shipped quantity", int((diff != 0).sum())))
    return out


# ------------------------------------------------------------------------------------------------- scenarios
def check_scenarios(t: Dict[str, pd.DataFrame], config: dict) -> List[CheckResult]:
    out = []
    snap = dt.date.fromisoformat(str(config["simulation"]["snapshot_date"]))
    pos = t["inventory_positions"]
    cur = pos[_to_date(pos.snapshot_date) == snap]
    so, use, par, prod, ro = (t["shipment_orders"], t["usage_history"], t["par_levels"], t["product_master"],
                              t["return_orders"])
    for s in config["scenarios"]:
        c, k, sid = s["customer_id"], s["sku"], s["scenario_id"]
        exp = s.get("expectations") or {}
        oh = int(cur[(cur.customer_id == c) & (cur.sku == k)].on_hand_qty.sum())
        tgt = (s.get("target_state") or {}).get("on_hand_qty")
        if tgt is not None:
            out.append(CheckResult(f"{sid}.current_inventory", oh == tgt, f"on hand {oh} (expected {tgt})"))
        pol = s.get("policy")
        if pol:
            row = par[(par.customer_id == c) & (par.sku == k)].iloc[0]
            ok = int(row.par_level) == pol["par_level"] and int(row.mandatory_minimum) == pol["mandatory_minimum"]
            out.append(CheckResult(f"{sid}.policy", ok, f"PAR {row.par_level}, mandatory minimum {row.mandatory_minimum}"))
        win = s.get("window")
        if win and "historical_consumption_window_qty" in exp:
            since = snap - dt.timedelta(days=int(win["days"]))
            q = int(use[(use.customer_id == c) & (use.sku == k) & (_to_date(use.usage_date) > since)].quantity_consumed.sum())
            out.append(CheckResult(f"{sid}.window_consumption", q == exp["historical_consumption_window_qty"],
                                   f"{q} consumed in last {win['days']} days"))
        if "unit_inventory_value" in exp:
            uc = float(prod[prod.sku == k].unit_cost.iloc[0])
            out.append(CheckResult(f"{sid}.unit_value", uc == exp["unit_inventory_value"], f"unit value ${uc:,.0f}"))
        orq = s.get("open_request")
        if orq:
            r = so[(so.scenario_id == sid) & (so.order_status == "PENDING_REVIEW")]
            ok = len(r) == 1 and int(r.requested_qty.iloc[0]) == orq["requested_qty"]
            out.append(CheckResult(f"{sid}.open_request", ok, f"pending request of {orq['requested_qty']} present"))
        if "par_only_baseline_qty" in exp and pol:
            base = max(0, pol["par_level"] - oh)
            out.append(CheckResult(f"{sid}.par_only_baseline", base == exp["par_only_baseline_qty"],
                                   f"PAR-only baseline {base}"))
        if "min_returns_last_12m" in exp:
            n = int(((ro.customer_id == c) & (ro.sku == k) & (_to_date(ro.return_date) > snap - dt.timedelta(days=365))).sum())
            out.append(CheckResult(f"{sid}.returns_12m", n >= exp["min_returns_last_12m"], f"{n} returns in last 12 months"))
        if "short_dated_qty" in exp:
            lots = t["lot_master"].set_index("lot_id")
            cc = cur[(cur.customer_id == c) & (cur.sku == k)]
            sd = int(cc[[lots.loc[l, "is_scenario_lot"] for l in cc.lot_id]].on_hand_qty.sum())
            out.append(CheckResult(f"{sid}.short_dated_qty", sd == exp["short_dated_qty"],
                                   f"{sd} units in the short-dated lot"))
        if exp.get("return_link_type") == "AMBIGUOUS":
            n = int(((ro.customer_id == c) & (ro.sku == k) & (ro.order_link_type == "AMBIGUOUS")).sum())
            out.append(CheckResult(f"{sid}.ambiguous_return", n >= 1, f"{n} ambiguous returns"))
    return out


def run_all(t: Dict[str, pd.DataFrame], config: dict) -> List[CheckResult]:
    snap = dt.date.fromisoformat(str(config["simulation"]["snapshot_date"]))
    return (check_referential_integrity(t) + check_inventory(t) + check_returns(t) + check_order_lifecycle(t, snap)
            + check_scenarios(t, config))


def summarize(t: Dict[str, pd.DataFrame]) -> dict:
    date_cols = {"usage_history": "usage_date", "shipment_orders": "request_date", "return_orders": "return_date",
                 "inventory_events": "event_date", "inventory_positions": "snapshot_date", "device_telemetry": "event_timestamp",
                 "stockout_events": "event_date"}
    out = {}
    for name, df in t.items():
        row = {"rows": int(len(df))}
        col = date_cols.get(name)
        if col and len(df):
            row["min_date"] = str(pd.to_datetime(df[col]).min())[:19]
            row["max_date"] = str(pd.to_datetime(df[col]).max())[:19]
        out[name] = row
    return out

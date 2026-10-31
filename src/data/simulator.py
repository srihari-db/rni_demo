"""Deterministic RNI operations simulator.

Generates a coherent, chronologically ordered synthetic history for Right Now Inventory (RNI) customer sites:

    masters  ->  daily demand  ->  weekly (simulated manual) replenishment requests  ->  SAP-style shipments
             ->  lot-level receipts / FEFO consumption / expiry disposal / returns  ->  inventory event ledger

Every inventory movement is written to a lot-level event ledger, so for any customer/SKU/lot

    opening + receipts - consumption - returns - disposal == closing

holds by construction (and is re-verified by ``src.data.quality``). Product *movement* (shipments, returns,
disposals) is kept separate from product *utilization* (``usage_history``).

The simulator does NOT produce forecasts or replenishment recommendations. Those are created downstream by
executing the forecasting pipeline and the decision engine on this data.

All entities and values are synthetic.
"""
from __future__ import annotations

import datetime as dt
import math
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import catalog

SIMULATOR_VERSION = "1.0.0"


# ----------------------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------------------
def _d(s) -> dt.date:
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(str(s))


def round_up_pack(qty: float, pack: int) -> int:
    if qty <= 0:
        return 0
    return int(math.ceil(qty / pack) * pack)


def _stable_rng(seed: int, *keys) -> np.random.Generator:
    """RNG keyed by stable identifiers so adding/removing entities never reshuffles other entities' data."""
    material = [seed] + [sum((i + 1) * ord(c) for i, c in enumerate(str(k))) for k in keys]
    return np.random.default_rng(material)


@dataclass
class Lot:
    lot_id: str
    sku: str
    mfg_date: dt.date
    release_date: dt.date
    expiry_date: dt.date
    is_scenario_lot: bool = False


@dataclass
class Pair:
    customer_id: str
    sku: str
    device_id: str
    profile: str
    params: dict
    par_level: int
    mandatory_minimum: int
    lead_time_days: int
    pack: int
    unit_cost: float
    shelf_life: int
    storage: str
    critical: bool
    p_excess: float
    return_propensity: float
    ordering_bias: float
    mean_daily_demand: float
    demand: np.ndarray = field(default=None, repr=False)
    lots: Dict[str, int] = field(default_factory=dict)          # lot_id -> qty on hand
    in_transit: int = 0
    frozen_from: Optional[int] = None                             # scenario window start (day index)
    scenario_id: Optional[str] = None
    last_shipment_lot: Optional[str] = None
    deliveries_by_lot: Dict[str, List[Tuple[str, int]]] = field(default_factory=lambda: defaultdict(list))

    @property
    def key(self):
        return (self.customer_id, self.sku)

    def on_hand(self) -> int:
        return int(sum(self.lots.values()))


# ----------------------------------------------------------------------------------------------------------------
# simulator
# ----------------------------------------------------------------------------------------------------------------
class RNISimulator:
    def __init__(self, config: dict):
        sim = config["simulation"]
        self.cfg = config
        self.seed = int(sim["seed"])
        self.start = _d(sim["start_date"])
        self.snapshot = _d(sim["snapshot_date"])
        self.n_days = (self.snapshot - self.start).days + 1
        self.review_period = int(sim.get("review_period_days", 7))
        self.pending_window = int(sim.get("pending_review_window_days", 2))
        self.telemetry_days = int(sim.get("telemetry_days", 30))
        self.telemetry_interval = int(sim.get("telemetry_interval_minutes", 15))
        self.scenarios = [s for s in config.get("scenarios", [])]
        self.scn_by_pair = {(s["customer_id"], s["sku"]): s for s in self.scenarios}

        # output buffers
        self.events: List[dict] = []
        self.usage: List[dict] = []
        self.stockouts: List[dict] = []
        self.order_lines: List[dict] = []
        self.allocations: List[dict] = []
        self.returns: List[dict] = []
        self.return_links: List[dict] = []
        self.snapshots: List[dict] = []
        self._order_seq: Dict[Tuple[str, int], int] = defaultdict(int)
        self._order_ids: Dict[Tuple[str, int], str] = {}
        self._return_seq: Dict[Tuple[str, int], int] = defaultdict(int)
        self._deliveries: Dict[int, List[dict]] = defaultdict(list)
        self._scripted: Dict[int, List[Tuple[Pair, dict]]] = defaultdict(list)

    # -------------------------------------------------------------------------------- dates
    def date(self, t: int) -> dt.date:
        return self.start + dt.timedelta(days=t)

    def t_of_offset(self, offset: int) -> int:
        return self.n_days - 1 + int(offset)

    # -------------------------------------------------------------------------------- masters
    def build_masters(self):
        rng = _stable_rng(self.seed, "masters")
        prod = pd.DataFrame(catalog.PRODUCTS, columns=catalog.PRODUCT_COLUMNS)
        for s in self.scenarios:
            for k, v in (s.get("product_overrides") or {}).items():
                prod.loc[prod.sku == s["sku"], k] = v
        margin = np.round(rng.uniform(1.05, 1.12, len(prod)), 3)
        prod["selling_price"] = np.round(prod.unit_cost * margin, 2)
        prod["manufacturer"] = [catalog.MANUFACTURERS[i % len(catalog.MANUFACTURERS)] for i in range(len(prod))]
        prod["cold_chain_required"] = prod.storage_type.isin(["REFRIGERATED", "FROZEN"])
        self.products = prod

        cust = pd.DataFrame(catalog.CUSTOMERS, columns=catalog.CUSTOMER_COLUMNS)
        cust["review_weekday"] = [int(i % 5) for i in range(len(cust))]          # Mon..Fri
        cust["onboarded_date"] = [self.start - dt.timedelta(days=int(d)) for d in rng.integers(200, 1500, len(cust))]
        self.customers = cust

        # devices: one per storage type the site needs
        dev_rows = []
        self._assign_rows = []
        prod_by_cat = prod.groupby("product_category")["sku"].apply(list).to_dict()
        for ci, c in cust.iterrows():
            crng = _stable_rng(self.seed, "assort", c.customer_id)
            cats = catalog.ASSORTMENT_BY_TYPE[c.customer_type]
            eligible = sorted({s for cat in cats for s in prod_by_cat.get(cat, [])})
            n = int(min(len(eligible), crng.integers(11, 17)))
            chosen = set(crng.choice(eligible, size=n, replace=False).tolist())
            chosen |= {s["sku"] for s in self.scenarios if s["customer_id"] == c.customer_id}
            storages = sorted(set(prod.set_index("sku").loc[sorted(chosen), "storage_type"]))
            dev_ids = {}
            for di, st in enumerate(storages, start=1):
                dev_id = f"RNI-DEV-{int(c.customer_id[-3:]):02d}{di:02d}"
                dev_ids[st] = dev_id
                dev_rows.append(dict(device_id=dev_id, customer_id=c.customer_id, device_type=catalog.DEVICE_TYPES[st],
                                     storage_type=st, firmware_version=f"4.{int(crng.integers(2, 6))}.{int(crng.integers(0, 9))}",
                                     install_date=c.onboarded_date + dt.timedelta(days=int(crng.integers(0, 60))),
                                     device_status="ACTIVE"))
            for sku in sorted(chosen):
                st = prod.set_index("sku").loc[sku, "storage_type"]
                self._assign_rows.append(dict(customer_id=c.customer_id, sku=sku, device_id=dev_ids[st]))
        self.devices = pd.DataFrame(dev_rows)

    # -------------------------------------------------------------------------------- lots
    def build_lots(self):
        self.lots: Dict[str, Lot] = {}
        self.lots_by_sku: Dict[str, List[Lot]] = defaultdict(list)
        for p in self.products.itertuples():
            first_mfg = self.start - dt.timedelta(days=int(p.shelf_life_days))
            k = 0
            mfg = first_mfg
            while mfg <= self.snapshot:
                lot_id = f"L{p.sku[-4:]}-{mfg:%y%m}{chr(65 + (k % 26))}"
                lot = Lot(lot_id, p.sku, mfg, mfg + dt.timedelta(days=21), mfg + dt.timedelta(days=int(p.shelf_life_days)))
                self.lots[lot_id] = lot
                self.lots_by_sku[p.sku].append(lot)
                mfg += dt.timedelta(days=30)
                k += 1

    def latest_released_lot(self, sku: str, on: dt.date, min_expiry: Optional[dt.date] = None) -> Lot:
        cands = [l for l in self.lots_by_sku[sku] if l.release_date <= on and (min_expiry is None or l.expiry_date > min_expiry)]
        return cands[-1]

    def warehouse_pick_lot(self, sku: str, ship_date: dt.date, rng) -> Lot:
        """Distribution-center FEFO: often ship the oldest released lot that still meets a minimum remaining
        shelf life (180-360 days), otherwise the newest release. Creates realistic short-dated stock at sites."""
        if rng.random() < 0.45:
            min_rem = ship_date + dt.timedelta(days=int(rng.integers(180, 361)))
            cands = [l for l in self.lots_by_sku[sku] if l.release_date <= ship_date and l.expiry_date > min_rem]
            if cands:
                return cands[0]
        return self.latest_released_lot(sku, ship_date)

    def scenario_lot(self, sku: str, expiry: dt.date) -> Lot:
        shelf = int(self.products.set_index("sku").loc[sku, "shelf_life_days"])
        mfg = expiry - dt.timedelta(days=shelf)
        lot = Lot(f"L{sku[-4:]}-{mfg:%y%m}X", sku, mfg, mfg + dt.timedelta(days=21), expiry, True)
        self.lots[lot.lot_id] = lot
        self.lots_by_sku[sku].append(lot)
        self.lots_by_sku[sku].sort(key=lambda l: l.release_date)
        return lot

    # -------------------------------------------------------------------------------- demand
    def _sample_demand(self, rng, profile: str, prm: dict, n: int) -> np.ndarray:
        days = [self.date(t) for t in range(n)]
        dow = np.array([d.weekday() for d in days])
        doy = np.array([d.timetuple().tm_yday for d in days])
        month = np.array([d.month for d in days])
        if profile == "REGULAR":
            rate = prm["daily_rate"] * np.where(dow >= 5, 0.6, 1.0) * (1 + prm.get("trend", 0.0) * np.arange(n) / n)
            return rng.poisson(np.maximum(rate, 0))
        if profile == "SEASONAL":
            season = 1 + prm["amplitude"] * np.cos(2 * np.pi * (doy - prm["peak_doy"]) / 365.25)
            rate = prm["daily_rate"] * np.maximum(season, 0.05) * np.where(dow >= 5, 0.5, 1.0)
            return rng.poisson(rate)
        if profile == "INTERMITTENT":
            hit = rng.random(n) < prm["event_probability"]
            size = rng.geometric(1.0 / prm["mean_event_size"], n)
            return np.where(hit, size, 0)
        if profile == "EMERGENCY":
            boost = np.where((month >= 5) & (month <= 9), prm.get("summer_boost", 1.0), 1.0)
            hit = rng.random(n) < prm["event_probability"] * boost
            size = 1 + rng.poisson(max(prm["mean_event_size"] - 1, 0), n)
            return np.where(hit, size, 0)
        raise ValueError(profile)

    @staticmethod
    def _mean_rate(profile: str, prm: dict) -> float:
        if profile == "REGULAR":
            return prm["daily_rate"] * (5 + 2 * 0.6) / 7
        if profile == "SEASONAL":
            return prm["daily_rate"] * (5 + 2 * 0.5) / 7
        if profile == "INTERMITTENT":
            return prm["event_probability"] * prm["mean_event_size"]
        return prm["event_probability"] * prm["mean_event_size"] * (1 + (prm.get("summer_boost", 1.0) - 1) * 5 / 12)

    def build_pairs(self):
        prod = self.products.set_index("sku")
        cust = self.customers.set_index("customer_id")
        self.pairs: List[Pair] = []
        par_rows, rule_rows = [], []
        for a in self._assign_rows:
            c, p = cust.loc[a["customer_id"]], prod.loc[a["sku"]]
            rng = _stable_rng(self.seed, "pair", a["customer_id"], a["sku"])
            scn = self.scn_by_pair.get((a["customer_id"], a["sku"]))
            profile = p.demand_profile
            size = float(c.size_factor)
            if profile == "REGULAR":
                prm = dict(daily_rate=float(rng.uniform(0.25, 2.6) * size * (0.4 if p.unit_cost > 2000 else 1.0)),
                           trend=float(rng.uniform(-0.15, 0.25)))
            elif profile == "SEASONAL":
                prm = dict(daily_rate=float(rng.uniform(0.6, 3.5) * size), amplitude=float(rng.uniform(0.6, 0.95)),
                           peak_doy=int(rng.integers(5, 30)))                 # winter respiratory season
            elif profile == "INTERMITTENT":
                prm = dict(event_probability=float(rng.uniform(0.015, 0.06) * size), mean_event_size=float(rng.uniform(1.2, 2.2)))
            else:
                prm = dict(event_probability=float(rng.uniform(0.003, 0.012) * size), mean_event_size=float(rng.uniform(2.0, 6.0)),
                           summer_boost=3.0 if p.product_category == "Antivenom & Antitoxin" else 1.0)
            if scn and scn.get("pre_window_demand"):
                pw = dict(scn["pre_window_demand"])
                profile = pw.pop("profile")
                prm.update(pw)
            mean = self._mean_rate(profile, prm)
            lead = int(catalog.LEAD_TIME_BY_REGION[c.region])
            pack = int(p.pack_size)
            if profile in ("REGULAR", "SEASONAL"):
                peak = mean * (1 + prm.get("amplitude", 0))
                par = round_up_pack(max(pack, peak * (lead + self.review_period) * rng.uniform(1.6, 2.4)), pack)
            elif profile == "INTERMITTENT":
                par = round_up_pack(max(2, prm["mean_event_size"] * rng.uniform(2.0, 4.0)), pack)
            else:
                par = round_up_pack(max(4, prm["mean_event_size"] * rng.uniform(1.5, 2.5)), pack)
            if p.critical_stock_flag:
                mmin = int(math.ceil(par * rng.uniform(0.55, 0.7)))
            else:
                mmin = max(1, int(math.ceil(par * rng.uniform(0.25, 0.45))))
            pol = (scn or {}).get("policy") or {}
            par, mmin, lead = int(pol.get("par_level", par)), int(pol.get("mandatory_minimum", mmin)), int(pol.get("lead_time_days", lead))
            beh = (scn or {}).get("behavior_overrides") or {}
            pair = Pair(a["customer_id"], a["sku"], a["device_id"], profile, prm, par, mmin, lead, pack, float(p.unit_cost),
                        int(p.shelf_life_days), p.storage_type, bool(p.critical_stock_flag),
                        float(beh.get("p_excess", c.p_excess)), float(beh.get("return_propensity", c.return_propensity)),
                        float(c.ordering_bias), mean)
            pair.demand = self._sample_demand(rng, profile, prm, self.n_days).astype(int)
            pair.scenario_id = scn["scenario_id"] if scn else None
            self.pairs.append(pair)
            par_rows.append(dict(customer_id=pair.customer_id, sku=pair.sku, par_level=par, mandatory_minimum=mmin,
                                 replenishment_lead_time_days=lead, review_period_days=self.review_period,
                                 stocking_policy_source="SIMULATED_CONTRACT", effective_date=self.start))
        self.par_levels = pd.DataFrame(par_rows)

        # dosing_rules = simulated STOCKING-POLICY metadata (never patient dosing)
        for p in self.products.itertuples():
            rr = _stable_rng(self.seed, "rules", p.sku)
            if p.critical_stock_flag:
                policy = "CRITICAL_MINIMUM_HOLD"
            elif p.demand_profile == "SEASONAL":
                policy = "SEASONAL_PREBUILD_WITH_PAR_CAP"
            elif p.demand_profile == "INTERMITTENT":
                policy = "MIN_MAX_REVIEW"
            else:
                policy = "PAR_REPLENISH"
            v1 = self.start - dt.timedelta(days=int(rr.integers(100, 400)))
            rule_rows.append(dict(sku=p.sku, rule_version="v1", approved_stocking_policy=policy,
                                  review_required=bool(p.critical_stock_flag or p.unit_cost >= 2500), effective_date=v1,
                                  superseded_date=None, policy_notes="Simulated stocking-policy metadata (not patient dosing)."))
            if rr.random() < 0.35:
                v2 = self.start + dt.timedelta(days=int(rr.integers(90, 600)))
                rule_rows[-1]["superseded_date"] = v2
                rule_rows.append(dict(sku=p.sku, rule_version="v2", approved_stocking_policy=policy,
                                      review_required=True, effective_date=v2, superseded_date=None,
                                      policy_notes="Simulated policy revision: human review required for all changes."))
        self.dosing_rules = pd.DataFrame(rule_rows)

    # -------------------------------------------------------------------------------- ledger primitives
    def _event(self, t, pair: Pair, lot_id: str, etype: str, qty: int, ref_type: str, ref_id: str):
        if qty == 0:
            return
        new = pair.lots.get(lot_id, 0) + qty
        assert new >= 0, f"negative lot balance {pair.key} {lot_id} {etype}"
        pair.lots[lot_id] = new
        self.events.append(dict(event_seq=len(self.events) + 1, event_date=self.date(t), customer_id=pair.customer_id,
                                device_id=pair.device_id, sku=pair.sku, lot_id=lot_id, event_type=etype,
                                quantity_delta=int(qty), reference_type=ref_type, reference_id=ref_id,
                                lot_balance_after=int(new)))

    def _fefo_lots(self, pair: Pair) -> List[str]:
        return sorted([l for l, q in pair.lots.items() if q > 0], key=lambda l: self.lots[l].expiry_date)

    def _order_id(self, t: int, customer_id: str) -> str:
        key = (customer_id, t)
        if key not in self._order_ids:
            self._order_ids[key] = f"SO-{self.date(t):%y%m%d}-{customer_id[-3:]}"
        return self._order_ids[key]

    # -------------------------------------------------------------------------------- orders / shipments
    def _create_order_line(self, t_req: int, pair: Pair, requested: int, rng, synthetic_excess: bool,
                           channel: str = "RNI_PORTAL", forced_lot: Optional[Lot] = None, force_status: Optional[str] = None,
                           scenario_id: Optional[str] = None, deliver_at: Optional[int] = None) -> dict:
        order_id = self._order_id(t_req, pair.customer_id)
        self._order_seq[(pair.customer_id, t_req)] += 1
        line_id = f"{order_id}-L{self._order_seq[(pair.customer_id, t_req)]:02d}"
        last = self.n_days - 1
        line = dict(order_id=order_id, order_line_id=line_id, customer_id=pair.customer_id, sku=pair.sku,
                    request_date=self.date(t_req), requested_qty=int(requested), approved_qty=None, shipped_qty=0,
                    shipment_date=None, delivered_date=None, order_status=None, decision_source="MANUAL_EXCEL_SIMULATED",
                    request_channel=channel, synthetic_excess_flag=bool(synthetic_excess), scenario_id=scenario_id,
                    sap_delivery_id=None)

        if force_status == "PENDING_REVIEW" or (force_status is None and t_req > last - self.pending_window):
            line["order_status"] = "PENDING_REVIEW"
            self.order_lines.append(line)
            return line

        # simulated FFF review of the manual request
        approved = requested
        status = "APPROVED"
        if force_status is None:
            r = rng.random()
            if requested > 3 * pair.par_level and r < 0.35:
                approved = max(pair.pack, round_up_pack(pair.par_level - pair.on_hand() - pair.in_transit, pair.pack))
            elif r < 0.04:
                status = "REJECTED"
            elif r < 0.05:
                status = "CANCELLED"
        if status in ("REJECTED", "CANCELLED"):
            line.update(approved_qty=0, order_status=status)
            self.order_lines.append(line)
            return line

        shipped = approved
        if force_status is None and rng.random() < 0.03 and approved >= 2 * pair.pack:
            shipped = max(pair.pack, int(approved * rng.uniform(0.5, 0.9)) // pair.pack * pair.pack)
        t_ship = t_req + 1 if deliver_at is None else deliver_at - pair.lead_time_days
        t_del = t_ship + pair.lead_time_days if deliver_at is None else deliver_at
        line.update(approved_qty=int(approved), shipped_qty=int(shipped))
        if t_ship > last:
            line.update(order_status="APPROVED", shipped_qty=0)
            self.order_lines.append(line)
            return line

        # lot allocation at ship date
        ship_date = self.date(t_ship)
        if forced_lot is not None:
            allocs = [(forced_lot, shipped)]
        else:
            lot = self.warehouse_pick_lot(pair.sku, ship_date, rng)
            if shipped >= 4 and rng.random() < 0.10:
                prev = self.latest_released_lot(pair.sku, ship_date - dt.timedelta(days=31))
                if prev.lot_id != lot.lot_id and prev.expiry_date > self.date(t_del) + dt.timedelta(days=60):
                    first = shipped // 2
                    allocs = [(lot, shipped - first), (prev, first)]
                else:
                    allocs = [(lot, shipped)]
            else:
                allocs = [(lot, shipped)]
        for lot, q in allocs:
            self.allocations.append(dict(order_line_id=line_id, lot_id=lot.lot_id, allocated_qty=int(q),
                                         expiry_date=lot.expiry_date))
        pair.last_shipment_lot = allocs[0][0].lot_id
        line.update(shipment_date=ship_date, sap_delivery_id=f"80{zlib.crc32(line_id.encode()) % 10**8:08d}")
        if t_del > last:
            line["order_status"] = "IN_TRANSIT"
            pair.in_transit += shipped
        else:
            line["delivered_date"] = self.date(t_del)
            line["order_status"] = "DELIVERED" if shipped == approved else "PARTIALLY_DELIVERED"
            pair.in_transit += shipped
            self._deliveries[t_del].append(dict(pair=pair, line_id=line_id, allocs=allocs, qty=shipped))
        self.order_lines.append(line)
        return line

    def _receive(self, t: int):
        for dlv in self._deliveries.pop(t, []):
            pair = dlv["pair"]
            for lot, q in dlv["allocs"]:
                self._event(t, pair, lot.lot_id, "RECEIPT", int(q), "ORDER_LINE", dlv["line_id"])
                pair.deliveries_by_lot[lot.lot_id].append((dlv["line_id"], int(q)))
            pair.in_transit -= dlv["qty"]

    # -------------------------------------------------------------------------------- returns
    def _return(self, t: int, pair: Pair, lot_id: str, qty: int, reason: str, rng) -> Optional[str]:
        qty = int(min(qty, pair.lots.get(lot_id, 0)))
        if qty <= 0:
            return None
        lot = self.lots[lot_id]
        assert lot.expiry_date > self.date(t), "cannot return expired product"
        key = (pair.customer_id, t)
        self._return_seq[key] += 1
        rid = f"RT-{self.date(t):%y%m%d}-{pair.customer_id[-3:]}-{self._return_seq[key]:02d}"
        lo, hi = catalog.RETURN_SHIPPING_BASE[pair.storage]
        cost = rng.uniform(lo, hi) + qty * rng.uniform(*catalog.RETURN_HANDLING_PER_UNIT)
        processing = rng.uniform(*catalog.RETURN_PROCESSING_COST[pair.storage])
        self._event(t, pair, lot_id, "RETURN", -qty, "RETURN", rid)
        candidates = [c for c in pair.deliveries_by_lot.get(lot_id, [])]
        if len(candidates) == 1:
            link_type, src = "SYNTHETIC_SINGLE_CANDIDATE", candidates[0][0]
        elif len(candidates) > 1:
            link_type, src = "AMBIGUOUS", None
        else:
            link_type, src = "UNLINKED_OPENING_STOCK", None
        for c, _q in candidates:
            self.return_links.append(dict(return_id=rid, order_line_id=c, link_type=link_type,
                                          link_confidence=round(1.0 / len(candidates), 3), is_synthetic_link=True))
        self.returns.append(dict(return_id=rid, customer_id=pair.customer_id, sku=pair.sku, device_id=pair.device_id,
                                 lot_id=lot_id, returned_qty=qty, return_date=self.date(t), return_reason=reason,
                                 return_shipping_cost=round(float(cost), 2),
                                 return_processing_cost=round(float(processing), 2), returned_value=round(qty * pair.unit_cost, 2),
                                 cold_chain_shipment=pair.storage != "ROOM_TEMP", lot_expiry_date=lot.expiry_date,
                                 source_order_line_id=src, order_link_type=link_type, scenario_id=pair.scenario_id))
        return rid

    def _monthly_return_review(self, t: int, pair: Pair, rng):
        today = self.date(t)
        oh = pair.on_hand()
        if oh > 1.4 * pair.par_level and rng.random() < pair.return_propensity:
            excess = oh - pair.par_level
            for lot_id in sorted(pair.lots, key=lambda l: self.lots[l].expiry_date, reverse=True):
                if excess <= 0:
                    break
                if pair.lots[lot_id] > 0 and (self.lots[lot_id].expiry_date - today).days >= 120:
                    q = min(excess, pair.lots[lot_id])
                    self._return(t, pair, lot_id, q, "EXCESS_STOCK", rng)
                    excess -= q
        cum_use = 0.0
        for lot_id in self._fefo_lots(pair):
            dte = (self.lots[lot_id].expiry_date - today).days
            usable = max(0.0, pair.mean_daily_demand * dte - cum_use)
            q = pair.lots[lot_id]
            cum_use += min(q, usable)
            surplus = int(q - usable)
            if 45 < dte <= 120 and surplus >= 1 and rng.random() < 0.5 * pair.return_propensity:
                self._return(t, pair, lot_id, surplus, "SHORT_DATED", rng)

    # -------------------------------------------------------------------------------- scenario shaping
    def _setup_scenarios(self):
        pairs = {p.key: p for p in self.pairs}
        for s in self.scenarios:
            pair = pairs[(s["customer_id"], s["sku"])]
            win = s.get("window")
            if win:
                pair.frozen_from = self.t_of_offset(-int(win["days"]))
                cons = win.get("consumption", {"mode": "profile"})
                if cons["mode"] == "scripted":
                    pair.demand[pair.frozen_from:] = 0
                    for e in cons.get("events", []):
                        pair.demand[self.t_of_offset(e["day_offset"])] += int(e["qty"])
            for e in s.get("scripted_events", []) or []:
                self._scripted[self.t_of_offset(e["day_offset"])].append((pair, e))

    def _anchor(self, t: int, pair: Pair, s: dict, rng):
        """At the window start, set the stock so the deterministic window reaches the scenario's target on-hand."""
        win = s["window"]
        snap = self.snapshot
        if win.get("reset_existing_stock"):
            for lot_id in list(pair.lots):
                if pair.lots[lot_id] > 0:
                    self._return(t, pair, lot_id, pair.lots[lot_id], "STOCK_ROTATION", rng)
        else:
            for lot_id in list(pair.lots):                      # lots that would expire inside the window
                if pair.lots[lot_id] > 0 and self.lots[lot_id].expiry_date <= snap + dt.timedelta(days=1):
                    self._return(t, pair, lot_id, pair.lots[lot_id], "SHORT_DATED", rng)
        future_demand = int(pair.demand[t:].sum())
        need = int(s["target_state"]["on_hand_qty"]) + future_demand - pair.on_hand() - pair.in_transit
        shipments = win.get("anchor_shipments") or [{"qty": "auto"}]
        fixed = sum(int(x["qty"]) for x in shipments if x["qty"] != "auto")
        for x in shipments:
            q = need - fixed if x["qty"] == "auto" else int(x["qty"])
            if q < 0:
                excess = -q
                for lot_id in sorted(pair.lots, key=lambda l: self.lots[l].expiry_date, reverse=True):
                    if excess <= 0:
                        break
                    take = min(excess, pair.lots[lot_id])
                    if take > 0:
                        self._return(t, pair, lot_id, take, "EXCESS_STOCK", rng)
                        excess -= take
                continue
            if q == 0:
                continue
            if x.get("lot_expiry_days_after_snapshot") is not None:
                lot = self.scenario_lot(pair.sku, snap + dt.timedelta(days=int(x["lot_expiry_days_after_snapshot"])))
            else:
                lot = self.latest_released_lot(pair.sku, self.date(t), min_expiry=snap + dt.timedelta(days=180))
            self._create_order_line(t - pair.lead_time_days - 1, pair, q, rng, False, channel="RNI_PORTAL",
                                    forced_lot=lot, force_status="DELIVER", scenario_id=None, deliver_at=t)
            self._receive(t)                                    # anchor shipment lands today

    def _run_scripted(self, t: int, pair: Pair, e: dict, rng):
        if e["type"] == "SHIPMENT":
            lot = None
            if e.get("lot") == "SAME_AS_LAST_SHIPMENT" and pair.last_shipment_lot:
                lot = self.lots[pair.last_shipment_lot]
            else:
                lot = self.latest_released_lot(pair.sku, self.date(t))
            self._create_order_line(t, pair, int(e["qty"]), rng, False, forced_lot=lot, force_status="DELIVER")
        elif e["type"] == "RETURN":
            lot_id = pair.last_shipment_lot
            self._return(t, pair, lot_id, int(e["qty"]), e.get("reason", "EXCESS_STOCK"), rng)

    # -------------------------------------------------------------------------------- main loop
    def run(self):
        self.build_masters()
        self.build_lots()
        self.build_pairs()
        self._setup_scenarios()
        cust_review = self.customers.set_index("customer_id")["review_weekday"].to_dict()
        rngs = {p.key: _stable_rng(self.seed, "ops", p.customer_id, p.sku) for p in self.pairs}

        # opening balances
        for p in self.pairs:
            rng = rngs[p.key]
            qty = round_up_pack(p.par_level * rng.uniform(0.7, 1.3), p.pack)
            lot_new = self.latest_released_lot(p.sku, self.start - dt.timedelta(days=int(rng.integers(10, 60))),
                                               min_expiry=self.start + dt.timedelta(days=90))
            lot_old = self.latest_released_lot(p.sku, self.start - dt.timedelta(days=int(rng.integers(120, 240))),
                                               min_expiry=self.start + dt.timedelta(days=30))
            split = qty // 3 if (qty >= 3 and lot_old.lot_id != lot_new.lot_id) else 0
            self._event(0, p, lot_new.lot_id, "OPENING_BALANCE", qty - split, "OPENING", "OPENING")
            if split:
                self._event(0, p, lot_old.lot_id, "OPENING_BALANCE", split, "OPENING", "OPENING")

        last = self.n_days - 1
        for t in range(self.n_days):
            today = self.date(t)
            self._receive(t)
            for p in self.pairs:
                rng = rngs[p.key]
                # 1) expiry disposal
                for lot_id in list(p.lots):
                    if p.lots[lot_id] > 0 and self.lots[lot_id].expiry_date <= today:
                        self._event(t, p, lot_id, "EXPIRY_DISPOSAL", -p.lots[lot_id], "EXPIRY", lot_id)
                # 2) scenario anchor at window start
                scn = self.scn_by_pair.get(p.key)
                if scn and p.frozen_from == t:
                    self._anchor(t, p, scn, rng)
                for (sp, e) in self._scripted.get(t, []):
                    if sp is p:
                        self._run_scripted(t, p, e, rng)
                # 3) consumption (utilization), FEFO
                need = int(p.demand[t])
                if need:
                    used = 0
                    for lot_id in self._fefo_lots(p):
                        take = min(need - used, p.lots[lot_id])
                        self._event(t, p, lot_id, "CONSUMPTION", -take, "USAGE", f"U-{today:%y%m%d}")
                        used += take
                        if used == need:
                            break
                    if used:
                        self.usage.append(dict(customer_id=p.customer_id, sku=p.sku, device_id=p.device_id,
                                               usage_date=today, quantity_consumed=int(used)))
                    if used < need:
                        self.stockouts.append(dict(customer_id=p.customer_id, sku=p.sku, event_date=today,
                                                   unmet_qty=int(need - used)))
                frozen = p.frozen_from is not None and t >= p.frozen_from
                # 4) monthly return review
                if today.day == 1 and not frozen and t > 0:
                    self._monthly_return_review(t, p, rng)
                # 5) weekly replenishment review (simulated manual Excel decision)
                if today.weekday() == cust_review[p.customer_id] and not frozen:
                    pos = p.on_hand() + p.in_transit
                    trigger = p.par_level * 0.85 if p.profile in ("REGULAR", "SEASONAL") else p.par_level - 0.5
                    if pos < trigger or pos < p.mandatory_minimum:
                        req = (p.par_level - pos) * p.ordering_bias * rng.lognormal(0, 0.2)
                        excess = bool(rng.random() < p.p_excess)
                        if excess:
                            req = max(req, p.par_level) * rng.uniform(1.8, 4.0)
                        req = max(p.pack, round_up_pack(req, p.pack))
                        self._create_order_line(t, p, req, rng, excess)
            # 6) month-end + final snapshots
            if (today + dt.timedelta(days=1)).day == 1 or t == last:
                for p in self.pairs:
                    for lot_id, q in p.lots.items():
                        if q > 0:
                            self.snapshots.append(dict(customer_id=p.customer_id, device_id=p.device_id, sku=p.sku,
                                                       lot_id=lot_id, on_hand_qty=int(q),
                                                       expiry_date=self.lots[lot_id].expiry_date, snapshot_date=today,
                                                       is_current=(t == last)))

        # open executive requests (raised after the last review, still awaiting decision)
        pairs = {p.key: p for p in self.pairs}
        for s in self.scenarios:
            orq = s.get("open_request")
            if orq:
                p = pairs[(s["customer_id"], s["sku"])]
                self._create_order_line(self.t_of_offset(orq.get("day_offset", -1)), p, int(orq["requested_qty"]),
                                        rngs[p.key], False, force_status="PENDING_REVIEW", scenario_id=s["scenario_id"])
        return self

    # -------------------------------------------------------------------------------- telemetry (bonus IoT)
    def build_telemetry(self, anomaly_device: Optional[str] = None) -> pd.DataFrame:
        devs = self.devices[self.devices.storage_type != "ROOM_TEMP"].sort_values("device_id")
        if anomaly_device is None:
            anomaly_device = devs[devs.customer_id == "CUST-007"].device_id.iloc[0]
        end = dt.datetime.combine(self.snapshot, dt.time(23, 45))
        n = self.telemetry_days * 24 * 60 // self.telemetry_interval
        ts = pd.date_range(end=end, periods=n, freq=f"{self.telemetry_interval}min")
        frames = []
        for d in devs.itertuples():
            rng = _stable_rng(self.seed, "iot", d.device_id)
            base_t = 5.0 if d.storage_type == "REFRIGERATED" else -25.0
            cyc = np.sin(np.arange(n) * 2 * np.pi / 8)                    # ~2h compressor cycle
            temp = base_t + 0.35 * cyc + rng.normal(0, 0.15, n)
            vib = 1.8 + 0.12 * (cyc > 0) + rng.normal(0, 0.12, n)
            status = np.where(cyc > 0, "RUNNING", "IDLE").astype(object)
            status[rng.random(n) < 0.02] = "DEFROST"
            if d.device_id == anomaly_device:
                ramp_start = n - 7 * 24 * 60 // self.telemetry_interval
                ramp = np.clip((np.arange(n) - ramp_start) / (n - ramp_start), 0, 1)
                vib = vib + 2.4 * ramp ** 1.5 + rng.normal(0, 0.08, n) * ramp
                temp = temp + 1.1 * ramp
                hl = (ramp > 0.3) & (rng.random(n) < 0.35 * ramp)
                status[hl] = "HIGH_LOAD"
            frames.append(pd.DataFrame(dict(device_id=d.device_id, customer_id=d.customer_id, event_timestamp=ts,
                                            temperature_c=np.round(temp, 2), vibration_mm_s=np.round(np.maximum(vib, 0), 3),
                                            compressor_status=status, door_open_events=rng.poisson(0.15, n))))
        self.anomaly_device = anomaly_device
        return pd.concat(frames, ignore_index=True)

    # -------------------------------------------------------------------------------- outputs
    def tables(self) -> Dict[str, pd.DataFrame]:
        assign = pd.DataFrame(self._assign_rows)
        prof = {p.key: p for p in self.pairs}
        assign["assignment_start_date"] = self.start
        assign["scenario_id"] = [prof[(r.customer_id, r.sku)].scenario_id for r in assign.itertuples()]
        lots = pd.DataFrame([dict(lot_id=l.lot_id, sku=l.sku, manufacture_date=l.mfg_date, release_date=l.release_date,
                                  expiry_date=l.expiry_date, is_scenario_lot=l.is_scenario_lot) for l in self.lots.values()])
        events = pd.DataFrame(self.events)
        events["event_id"] = ["EV-%08d" % i for i in events.event_seq]
        snaps = pd.DataFrame(self.snapshots)
        scen = pd.DataFrame([dict(scenario_id=s["scenario_id"], scenario_name=s["name"], scenario_type=s["scenario_type"],
                                  customer_id=s["customer_id"], sku=s["sku"], narrative=s.get("narrative", "").strip(),
                                  optional=bool(s.get("optional", False)),
                                  requested_qty=(s.get("open_request") or {}).get("requested_qty"),
                                  expected_risk_category=(s.get("expectations") or {}).get("risk_category"))
                             for s in self.scenarios])
        cust = self.customers.drop(columns=["size_factor", "ordering_bias", "p_excess", "return_propensity"]).copy()
        out = dict(
            customer_master=cust,
            product_master=self.products.drop(columns=["demand_profile"]),
            rni_devices=self.devices,
            customer_product_assignments=assign,
            par_levels=self.par_levels,
            dosing_rules=self.dosing_rules,
            lot_master=lots,
            usage_history=pd.DataFrame(self.usage),
            stockout_events=pd.DataFrame(self.stockouts, columns=["customer_id", "sku", "event_date", "unmet_qty"]),
            shipment_orders=pd.DataFrame(self.order_lines),
            shipment_lot_allocations=pd.DataFrame(self.allocations),
            return_orders=pd.DataFrame(self.returns),
            return_order_links=pd.DataFrame(self.return_links),
            inventory_events=events,
            inventory_positions=snaps,
            scenario_registry=scen,
            device_telemetry=self.build_telemetry(),
            # behavioral ground truth kept separate from operational tables (never exposed to Genie / App)
            simulation_ground_truth=pd.DataFrame([dict(customer_id=p.customer_id, sku=p.sku, demand_profile=p.profile,
                                                       mean_daily_demand=round(p.mean_daily_demand, 4),
                                                       p_excess=p.p_excess, return_propensity=p.return_propensity,
                                                       ordering_bias=p.ordering_bias) for p in self.pairs]),
        )
        return out


def simulate(config: dict) -> Dict[str, pd.DataFrame]:
    return RNISimulator(config).run().tables()

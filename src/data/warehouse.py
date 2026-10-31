"""App data access: parameterized, read-only queries against the approved Gold views only.

The App, the AI/BI dashboard and the Genie agent share the same Gold views (``APPROVED_GOLD_OBJECTS``), so every
screen uses the same metric definitions. Each app query is declared once in ``QUERY_SPECS`` (view, filters,
ordering) and rendered either to parameterized SQL (``GoldRepository``) or applied to pre-loaded Gold frames
(``FrameRepository``, used by the automated app smoke tests). No method accepts free-form SQL from users.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

import pandas as pd

log = logging.getLogger("rni.warehouse")

APPROVED_GOLD_OBJECTS = (
    "as_of", "dim_customer", "dim_product", "inventory_lots_current", "inventory_exposure_current",
    "expiry_risk_horizon", "consumption_vs_shipments_monthly", "usage_weekly", "returns_detail",
    "demand_forecasts", "demand_forecast_weekly", "replenishment_recommendations", "shipment_review_queue",
    "inventory_value_metrics", "kpi_executive", "device_telemetry_hourly", "device_health",
)

# key -> (gold view, filter params (equality), order by)
QUERY_SPECS: Dict[str, Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = {
    "kpis": ("kpi_executive", (), ()),
    "exposure": ("inventory_exposure_current", (), ("customer_id", "sku")),
    "review_queue": ("shipment_review_queue", (), ("review_priority",)),
    "consumption_monthly": ("consumption_vs_shipments_monthly", (), ("month",)),
    "returns": ("returns_detail", (), ("return_date",)),
    "expiry": ("expiry_risk_horizon", (), ("expiry_horizon_order",)),
    "customers": ("dim_customer", (), ("customer_id",)),
    "products": ("dim_product", (), ("sku",)),
    "value_metrics": ("inventory_value_metrics", (), ("customer_id", "sku")),
    "pair_recs": ("replenishment_recommendations", ("customer_id", "sku"), ("recommendation_id",)),
    "pair_lots": ("inventory_lots_current", ("customer_id", "sku"), ("expiry_date",)),
    "pair_usage_weekly": ("usage_weekly", ("customer_id", "sku"), ("week_start",)),
    "pair_forecast": ("demand_forecasts", ("customer_id", "sku"), ("forecast_horizon",)),
    "pair_forecast_weekly": ("demand_forecast_weekly", ("customer_id", "sku"), ("week_start",)),
    "pair_returns": ("returns_detail", ("customer_id", "sku"), ("return_date",)),
    "device_health": ("device_health", (), ("device_id",)),
    "device_hourly": ("device_telemetry_hourly", ("device_id",), ("hour",)),
    "device_lots": ("inventory_lots_current", ("device_id",), ("expiry_date",)),
}


def referenced_gold_objects(sql: str, catalog: str) -> set:
    return set(re.findall(rf"{re.escape(catalog)}\.gold\.(\w+)", sql))


def render_sql(key: str, gold: str) -> str:
    view, filters, order = QUERY_SPECS[key]
    sql = f"SELECT * FROM {gold}.{view}"
    if filters:
        sql += " WHERE " + " AND ".join(f"{f} = :{f}" for f in filters)
    if order:
        sql += " ORDER BY " + ", ".join(order)
    return sql


class _Base:
    catalog: str
    gold: str

    def query(self, key: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        raise NotImplementedError

    def run_curated(self, sql: str) -> pd.DataFrame:
        raise NotImplementedError


class GoldRepository(_Base):
    """SQL warehouse backend (Databricks App). Auth: the app service principal via SDK Config()."""

    def __init__(self, catalog: Optional[str] = None, warehouse_id: Optional[str] = None):
        self.catalog = catalog or os.environ.get("RNI_CATALOG", "rni_demo")
        self.warehouse_id = warehouse_id or os.environ.get("DATABRICKS_WAREHOUSE_ID")
        self.gold = f"{self.catalog}.gold"
        self._conn = None

    def _connect(self):
        from databricks import sql
        from databricks.sdk.core import Config
        cfg = Config()
        if not self.warehouse_id:
            raise RuntimeError("DATABRICKS_WAREHOUSE_ID is not configured (app resource 'sql-warehouse').")
        return sql.connect(server_hostname=cfg.host.replace("https://", ""),
                           http_path=f"/sql/1.0/warehouses/{self.warehouse_id}",
                           credentials_provider=lambda: cfg.authenticate)

    def _run(self, sql: str, params: Optional[Dict[str, Any]], retries: int = 2) -> pd.DataFrame:
        objs = referenced_gold_objects(sql, self.catalog)
        if not objs or not objs <= set(APPROVED_GOLD_OBJECTS):
            raise PermissionError(f"query touches non-approved objects: {objs}")
        last = None
        for attempt in range(retries + 1):
            try:
                if self._conn is None:
                    self._conn = self._connect()
                with self._conn.cursor() as cur:
                    cur.execute(sql, params or {})
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description]
                return pd.DataFrame([tuple(r) for r in rows], columns=cols)
            except PermissionError:
                raise
            except Exception as e:  # reconnect on stale sessions / transient warehouse errors
                last = e
                log.warning("query failed (attempt %s): %s", attempt + 1, e)
                self._conn = None
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("Data service temporarily unavailable") from last

    def query(self, key: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        return self._run(render_sql(key, self.gold), params)

    def run_curated(self, sql: str) -> pd.DataFrame:
        """Only for the verified example SQL in src/genie/space_config.py (never user text)."""
        return self._run(sql, None)


class FrameRepository(_Base):
    """Same query specs evaluated over pre-loaded Gold view frames (tests / offline rendering)."""

    def __init__(self, frames: Dict[str, pd.DataFrame], catalog: str = "rni_demo"):
        self.frames = frames
        self.catalog = catalog
        self.gold = f"{catalog}.gold"

    def query(self, key: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        view, filters, order = QUERY_SPECS[key]
        df = self.frames[view].copy()
        for f in filters:
            df = df[df[f] == (params or {})[f]]
        if order:
            df = df.sort_values(list(order))
        return df.reset_index(drop=True)

    def run_curated(self, sql: str) -> pd.DataFrame:
        raise RuntimeError("curated SQL requires a SQL warehouse")

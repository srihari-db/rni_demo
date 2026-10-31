"""Shared runtime helpers for Databricks job scripts (paths, config, Spark table I/O, ownership guard)."""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List

log = logging.getLogger("rni")
MANAGED_PROP = "rni_demo.managed"

# synthetic source adapters: which simulated upstream system each extract represents
SOURCE_SYSTEM = {
    "customer_master": "SIM_RNI_CLOUDSQL_MYSQL", "product_master": "SIM_RNI_CLOUDSQL_MYSQL",
    "rni_devices": "SIM_RNI_CLOUDSQL_MYSQL", "customer_product_assignments": "SIM_RNI_CLOUDSQL_MYSQL",
    "par_levels": "SIM_RNI_CLOUDSQL_MYSQL", "dosing_rules": "SIM_RNI_CLOUDSQL_MYSQL",
    "lot_master": "SIM_SAP", "usage_history": "SIM_RNI_CLOUDSQL_MYSQL", "stockout_events": "SIM_RNI_CLOUDSQL_MYSQL",
    "inventory_events": "SIM_RNI_CLOUDSQL_MYSQL", "inventory_positions": "SIM_RNI_CLOUDSQL_MYSQL",
    "shipment_orders": "SIM_SAP", "shipment_lot_allocations": "SIM_SAP", "return_orders": "SIM_SAP",
    "return_order_links": "SIM_RECONCILIATION", "device_telemetry": "SIM_CLEARBLADE_PUBSUB",
    "scenario_registry": "DEMO_CONFIG", "simulation_ground_truth": "SIM_GROUND_TRUTH",
}


def repo_root() -> Path:
    try:
        here = Path(__file__).resolve()
        return here.parents[2]
    except NameError:  # pragma: no cover
        return Path(os.getcwd())


def ensure_repo_on_path():
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def base_args(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--catalog", default=os.environ.get("RNI_CATALOG", "rni_demo"))
    p.add_argument("--root", default=None, help="Bundle file root (serverless tasks lack __file__)")
    p.add_argument("--config", default=str(repo_root() / "config" / "demo_scenarios.yaml"))
    p.add_argument("--rules", default=str(repo_root() / "config" / "business_rules.yaml"))
    return p


def load_yaml(path: str) -> dict:
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


def get_spark():
    try:
        from databricks.connect import DatabricksSession  # type: ignore
        return DatabricksSession.builder.getOrCreate()
    except Exception:
        from pyspark.sql import SparkSession
        return SparkSession.builder.getOrCreate()


def sql_statements(path: str, catalog: str) -> List[str]:
    text = Path(path).read_text().replace("{{catalog}}", catalog)
    text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in re.split(r";\s*\n", text) if s.strip()]


def replaced_tables(statements: Iterable[str]) -> List[str]:
    out = []
    for s in statements:
        m = re.match(r"CREATE OR REPLACE TABLE\s+([\w.]+)", s, re.I)
        if m:
            out.append(m.group(1))
    return out


def guard_managed(spark, tables: Iterable[str]):
    """Refuse to replace any existing table that this project did not create (no TBLPROPERTY marker)."""
    for t in tables:
        if spark.catalog.tableExists(t):
            props = {r.key: r.value for r in spark.sql(f"SHOW TBLPROPERTIES {t}").collect()}
            if props.get(MANAGED_PROP) != "true":
                raise RuntimeError(f"Refusing to replace {t}: it exists and is not marked {MANAGED_PROP}=true. "
                                   f"Get explicit approval and drop it manually if it should be overwritten.")


def run_sql_file(spark, path: str, catalog: str):
    stmts = sql_statements(path, catalog)
    guard_managed(spark, replaced_tables(stmts))
    for s in stmts:
        log.info("SQL: %s", s.splitlines()[0][:120])
        spark.sql(s)
    return len(stmts)


def _conform(pdf, schema):
    """Coerce a pandas frame to the Spark target schema (column order, null handling, numeric/date types)."""
    import pandas as pd
    from pyspark.sql import types as T
    out = pd.DataFrame(index=pdf.index)
    for f in schema.fields:
        col = pdf[f.name] if f.name in pdf.columns else pd.Series([None] * len(pdf), index=pdf.index)
        dt_ = f.dataType
        if isinstance(dt_, (T.IntegerType, T.LongType, T.ShortType)):
            out[f.name] = pd.to_numeric(col, errors="coerce").round().astype("Int64")
        elif isinstance(dt_, (T.DoubleType, T.FloatType)):
            out[f.name] = pd.to_numeric(col, errors="coerce").astype(float)
        elif isinstance(dt_, T.BooleanType):
            out[f.name] = col.astype("boolean")
        elif isinstance(dt_, T.DateType):
            v = pd.to_datetime(col, errors="coerce")
            out[f.name] = [None if pd.isna(x) else x.date() for x in v]
        elif isinstance(dt_, T.TimestampType):
            out[f.name] = pd.to_datetime(col, errors="coerce")
        else:
            out[f.name] = [None if (x is None or (isinstance(x, float) and pd.isna(x))) else str(x) for x in col]
    return out


def write_pandas(spark, pdf, table: str, mode: str = "overwrite"):
    """Write a pandas frame into an existing (DDL-defined) table, conforming to the target schema."""
    schema = spark.table(table).schema
    sdf = spark.createDataFrame(_conform(pdf, schema), schema=schema)
    sdf.write.mode(mode).insertInto(table, overwrite=(mode == "overwrite"))
    return len(pdf)


def to_pandas(spark, table: str, where: str = None):
    q = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "")
    return spark.sql(q).toPandas()


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

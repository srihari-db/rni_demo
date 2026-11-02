"""Transactional persistence for investigation cases.

* ``LakebaseCaseStore`` — Lakebase Postgres (Autoscaling). Connection details come from the Databricks App
  ``postgres`` resource (PGHOST / PGDATABASE / PGUSER / PGPORT env vars); the password is a short-lived OAuth
  credential generated for the app's service principal and refreshed before expiry. No credentials in code.
* ``SqliteCaseStore`` — clearly labeled DEMO-ONLY fallback (ephemeral container storage) used if Lakebase is not
  configured, so the executive demo never depends on Lakebase availability.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
import threading
import time
from typing import List, Optional

from ..agents.cases import InvestigationCase

log = logging.getLogger("rni.store")

SCHEMA = "rni_ops"
DDL = [
    f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.investigation_cases (
        case_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, customer_name TEXT, sku TEXT NOT NULL, product_name TEXT,
        order_line_id TEXT, recommendation_id TEXT, requested_qty INTEGER, recommended_qty INTEGER,
        human_approved_qty INTEGER, risk_category TEXT, evidence TEXT, ai_summary TEXT, risk_explanation TEXT,
        proposed_next_action TEXT, missing_information TEXT, summary_source TEXT, status TEXT NOT NULL,
        reviewer TEXT, reviewer_comments TEXT, created_by TEXT, sap_action TEXT,
        created_at TIMESTAMP, updated_at TIMESTAMP)""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.planner_reviews (
        review_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, from_status TEXT, to_status TEXT, reviewer TEXT,
        comments TEXT, reviewed_at TIMESTAMP)""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.decision_overrides (
        override_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, engine_recommended_qty INTEGER, human_approved_qty INTEGER,
        reviewer TEXT, reason TEXT, created_at TIMESTAMP)""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.agent_activity (
        activity_id TEXT PRIMARY KEY, case_id TEXT, activity TEXT, actor TEXT, detail TEXT, created_at TIMESTAMP)""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.user_feedback (
        feedback_id TEXT PRIMARY KEY, screen TEXT, question TEXT, rating INTEGER, comment TEXT, user_email TEXT,
        created_at TIMESTAMP)""",
]
CASE_COLS = ["case_id", "customer_id", "customer_name", "sku", "product_name", "order_line_id", "recommendation_id",
             "requested_qty", "recommended_qty", "human_approved_qty", "risk_category", "evidence", "ai_summary",
             "risk_explanation", "proposed_next_action", "missing_information", "summary_source", "status", "reviewer",
             "reviewer_comments", "created_by", "sap_action", "created_at", "updated_at"]


def _uid(prefix):
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _row(case: InvestigationCase) -> tuple:
    d = case.to_dict()
    d["evidence"] = json.dumps(d["evidence"], default=str)
    d["missing_information"] = json.dumps(d["missing_information"])
    return tuple(d[c] for c in CASE_COLS)


def _case(row: dict) -> InvestigationCase:
    r = dict(row)
    r["evidence"] = json.loads(r["evidence"] or "{}")
    r["missing_information"] = json.loads(r["missing_information"] or "[]")
    for k in ("created_at", "updated_at"):
        if isinstance(r[k], str):
            r[k] = dt.datetime.fromisoformat(r[k])
    return InvestigationCase(**{k: r[k] for k in CASE_COLS})


class _BaseStore:
    label = ""
    ph = "%s"

    def _exec(self, sql: str, params=(), fetch=False):
        raise NotImplementedError

    def init(self):
        for s in DDL:
            self._exec(self._ddl(s))

    def _ddl(self, s):
        return s

    def _t(self, name):
        return f"{SCHEMA}.{name}"

    def save_case(self, case: InvestigationCase):
        cols = ", ".join(CASE_COLS)
        ph = ", ".join([self.ph] * len(CASE_COLS))
        upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in CASE_COLS if c != "case_id")
        self._exec(f"INSERT INTO {self._t('investigation_cases')} ({cols}) VALUES ({ph}) "
                   f"ON CONFLICT (case_id) DO UPDATE SET {upd}", _row(case))

    def get_case(self, case_id: str) -> Optional[InvestigationCase]:
        rows = self._exec(f"SELECT {', '.join(CASE_COLS)} FROM {self._t('investigation_cases')} WHERE case_id = {self.ph}",
                          (case_id,), fetch=True)
        return _case(rows[0]) if rows else None

    def list_cases(self, limit: int = 200) -> List[InvestigationCase]:
        rows = self._exec(f"SELECT {', '.join(CASE_COLS)} FROM {self._t('investigation_cases')} "
                          f"ORDER BY updated_at DESC LIMIT {int(limit)}", fetch=True)
        return [_case(r) for r in rows]

    def record_review(self, case: InvestigationCase, from_status: str):
        self._exec(f"INSERT INTO {self._t('planner_reviews')} VALUES ({', '.join([self.ph] * 7)})",
                   (_uid("REV"), case.case_id, from_status, case.status, case.reviewer, case.reviewer_comments, case.updated_at))
        if case.human_approved_qty is not None and case.human_approved_qty != case.recommended_qty:
            self._exec(f"INSERT INTO {self._t('decision_overrides')} VALUES ({', '.join([self.ph] * 7)})",
                       (_uid("OVR"), case.case_id, case.recommended_qty, case.human_approved_qty, case.reviewer,
                        case.reviewer_comments, case.updated_at))
        self.save_case(case)

    def log_activity(self, case_id: Optional[str], activity: str, actor: str, detail: dict):
        self._exec(f"INSERT INTO {self._t('agent_activity')} VALUES ({', '.join([self.ph] * 6)})",
                   (_uid("ACT"), case_id, activity, actor, json.dumps(detail, default=str),
                    dt.datetime.now(dt.timezone.utc).replace(microsecond=0)))

    def reset_cases(self, actor: str) -> int:
        """Delete every case with its reviews, overrides and activity; user feedback is kept. Returns cases deleted."""
        n = len(self._exec(f"SELECT case_id FROM {self._t('investigation_cases')}", fetch=True))
        for t in ("planner_reviews", "decision_overrides", "agent_activity", "investigation_cases"):
            self._exec(f"DELETE FROM {self._t(t)}")
        self.log_activity(None, "CASES_RESET", actor, {"cases_deleted": n})
        return n

    def save_feedback(self, screen: str, question: str, rating: int, comment: str, user_email: str):
        self._exec(f"INSERT INTO {self._t('user_feedback')} VALUES ({', '.join([self.ph] * 7)})",
                   (_uid("FB"), screen, question, int(rating), comment, user_email,
                    dt.datetime.now(dt.timezone.utc).replace(microsecond=0)))


class SqliteCaseStore(_BaseStore):
    label = "DEMO-ONLY local store (ephemeral) — Lakebase not configured"
    ph = "?"

    def __init__(self, path: str = None):
        self.path = path or os.environ.get("RNI_SQLITE_PATH", "/tmp/rni_cases.db")
        self._lock = threading.Lock()
        self.init()

    def _ddl(self, s):
        return "SELECT 1" if s.startswith("CREATE SCHEMA") else s.replace(f"{SCHEMA}.", f"{SCHEMA}_")

    def _t(self, name):
        return f"{SCHEMA}_{name}"

    def _exec(self, sql, params=(), fetch=False):
        sql = sql.replace(f"{SCHEMA}.", f"{SCHEMA}_")
        with self._lock, sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(sql, tuple(str(p) if isinstance(p, dt.datetime) else p for p in params))
            return [dict(r) for r in cur.fetchall()] if fetch else None


class LakebaseCaseStore(_BaseStore):
    label = "Lakebase Postgres (Autoscaling)"

    def __init__(self, endpoint: Optional[str] = None, workspace_client=None):
        self.host = os.environ["PGHOST"]
        self.dbname = os.environ.get("PGDATABASE", "databricks_postgres")
        self.port = int(os.environ.get("PGPORT", "5432"))
        self.endpoint = endpoint or os.environ.get("LAKEBASE_ENDPOINT")
        self._w = workspace_client
        self._conn = None
        self._token_at = 0.0
        self._lock = threading.Lock()
        self.user = os.environ.get("PGUSER") or self.w.current_user.me().user_name
        self.init()

    @property
    def w(self):
        if self._w is None:
            from databricks.sdk import WorkspaceClient
            self._w = WorkspaceClient()
        return self._w

    def _password(self) -> str:
        try:
            if self.endpoint:
                return self.w.postgres.generate_database_credential(endpoint=self.endpoint).token
        except Exception as e:
            log.info("generate_database_credential unavailable (%s); using workspace OAuth token", e)
        return self.w.config.oauth_token().access_token

    def _connection(self):
        import psycopg
        if self._conn is None or self._conn.closed or time.time() - self._token_at > 45 * 60:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()
            self._conn = psycopg.connect(host=self.host, dbname=self.dbname, user=self.user, port=self.port,
                                         password=self._password(), sslmode="require", autocommit=True,
                                         connect_timeout=15)
            self._token_at = time.time()
        return self._conn

    def _exec(self, sql, params=(), fetch=False):
        from psycopg.rows import dict_row
        with self._lock:
            for attempt in range(2):
                try:
                    with self._connection().cursor(row_factory=dict_row) as cur:
                        cur.execute(sql, params)
                        return cur.fetchall() if fetch else None
                except Exception as e:
                    if attempt:
                        raise
                    log.warning("Lakebase error, reconnecting: %s", e)
                    self._conn = None


def get_store():
    """Lakebase if configured and reachable, else the labeled demo-only fallback."""
    if os.environ.get("PGHOST"):
        try:
            return LakebaseCaseStore()
        except Exception as e:
            log.warning("Lakebase unavailable (%s); falling back to demo-only store", e)
    return SqliteCaseStore()

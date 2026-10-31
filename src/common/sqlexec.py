"""Run SQL on a SQL warehouse through the Statement Execution API (used by setup scripts run from a laptop/CI)."""
from __future__ import annotations

import time

import pandas as pd


def run(w, warehouse_id: str, sql: str, timeout_s: int = 300) -> pd.DataFrame:
    from databricks.sdk.service.sql import Disposition, Format, StatementState
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=warehouse_id, wait_timeout="50s",
                                                disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
    t0 = time.time()
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.time() - t0 > timeout_s:
            raise TimeoutError(sql[:120])
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{r.status.state}: {r.status.error.message if r.status.error else ''}\n{sql[:300]}")
    cols = [c.name for c in r.manifest.schema.columns] if r.manifest and r.manifest.schema else []
    rows = (r.result.data_array or []) if r.result else []
    return pd.DataFrame(rows, columns=cols)

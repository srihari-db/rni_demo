"""Least-privilege Unity Catalog grants for the Databricks App service principal: read-only on the gold schema.
(The warehouse, Genie space, serving endpoint and Lakebase permissions are granted through the app's resources.)"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.sqlexec import run  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", default="rni_demo")
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--app-name", default="rni-command-center")
    a = p.parse_args()
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    sp = w.apps.get(a.app_name).service_principal_client_id
    for sql in [f"GRANT USE CATALOG ON CATALOG {a.catalog} TO `{sp}`",
                f"GRANT USE SCHEMA ON SCHEMA {a.catalog}.gold TO `{sp}`",
                f"GRANT SELECT ON SCHEMA {a.catalog}.gold TO `{sp}`"]:
        run(w, a.warehouse_id, sql)
        print("OK", sql)


if __name__ == "__main__":
    main()

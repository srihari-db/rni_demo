"""Create/update and publish the AI/BI dashboard 'RNI Executive Inventory Intelligence'.

Every dataset reads the shared Gold views (same definitions as the App and Genie). Each dataset query is executed
on the warehouse first; the script aborts if any query fails or returns no rows.

Usage: python scripts/setup_dashboard.py --warehouse-id <id> [--catalog rni_demo] [--dashboard-id <id>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common.sqlexec import run  # noqa: E402

TITLE = "RNI Executive Inventory Intelligence"
USD = {"type": "number-currency", "currencyCode": "USD", "abbreviation": "compact",
       "decimalPlaces": {"type": "max", "places": 1}}


def datasets(g):
    return {
        "ds_metrics": f"""SELECT region, customer_name, product_category, product_name, inventory_value,
              potential_excess_exposure_value, potential_excess_value, pending_request_exposure_value, near_expiry_value,
              returned_value, avoidable_logistics_cost_12m, requests_requiring_review
            FROM {g}.inventory_value_metrics""",
        "ds_exposure": f"""SELECT region, customer_name, product_category, product_name, bucket, value
            FROM {g}.inventory_exposure_current
            LATERAL VIEW stack(3, 'Excess above PAR', excess_value, 'Approaching expiry (<=90d)', near_expiry_value,
                               'Healthy', healthy_value) b AS bucket, value""",
        "ds_monthly": f"""SELECT month, region, customer_name, product_category, product_name, series, value
            FROM {g}.consumption_vs_shipments_monthly
            LATERAL VIEW stack(2, 'Shipped to sites (movement)', shipped_value, 'Consumed at sites (utilization)', consumed_value) s AS series, value""",
        "ds_returns": f"""SELECT return_month, region, customer_name, product_category, product_name, returned_value,
              return_logistics_cost,
              CASE WHEN potentially_avoidable THEN 'Over-allocation (potentially avoidable)' ELSE 'Short-dated / other' END AS return_type
            FROM {g}.returns_detail WHERE in_last_12_months""",
        "ds_top10": f"""SELECT customer_name, region, SUM(potential_excess_value) AS excess_on_hand,
              SUM(pending_request_exposure_value) AS pending_request_exposure,
              SUM(potential_excess_exposure_value) AS potential_excess_exposure
            FROM {g}.inventory_value_metrics GROUP BY customer_name, region
            ORDER BY potential_excess_exposure DESC LIMIT 10""",
        "ds_expiry": f"""SELECT region, customer_name, product_category, product_name,
              CONCAT(CAST(expiry_horizon_order AS STRING), '. ', expiry_horizon) AS expiry_horizon, inventory_value
            FROM {g}.expiry_risk_horizon""",
        "ds_queue": f"""SELECT review_priority, customer_name, region, product_category, product_name, requested_qty, recommended_qty,
              on_hand_qty, par_level, consumed_last_120d, risk_category, potential_exposure_value, review_reason
            FROM {g}.shipment_review_queue WHERE human_review_required""",
    }


def text(name, md, x, y, w, h):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": [md]}}, "position": {"x": x, "y": y, "width": w, "height": h}}


def counter(name, ds, field, title, x, y, fmt=True):
    enc = {"fieldName": f"sum({field})", "displayName": title}
    if fmt:
        enc["format"] = USD
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
        "datasetName": ds, "fields": [{"name": f"sum({field})", "expression": f"SUM(`{field}`)"}], "disaggregated": False}}],
        "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": enc},
                 "frame": {"showTitle": True, "title": title}}},
        "position": {"x": x, "y": y, "width": 1, "height": 3}}


def bar(name, ds, x_field, y_field, color, title, pos, horizontal=False, x_date=False, group=False):
    fields = [{"name": x_field, "expression": f"`{x_field}`" if not x_date else f'DATE_TRUNC("MONTH", `{x_field}`)'},
              {"name": f"sum({y_field})", "expression": f"SUM(`{y_field}`)"}]
    if x_date:
        fields[0]["name"] = f"monthly({x_field})"
    if color:
        fields.append({"name": color, "expression": f"`{color}`"})
    cat = {"fieldName": fields[0]["name"], "scale": {"type": "temporal" if x_date else "categorical"}, "displayName": x_field.replace("_", " ").title()}
    val = {"fieldName": f"sum({y_field})", "scale": {"type": "quantitative"}, "displayName": "USD", "format": USD}
    enc = {"x": val, "y": cat} if horizontal else {"x": cat, "y": val}
    if color:
        enc["color"] = {"fieldName": color, "scale": {"type": "categorical"}, "displayName": color.replace("_", " ").title()}
    spec = {"version": 3, "widgetType": "bar", "encodings": enc, "frame": {"showTitle": True, "title": title}}
    if group:
        spec["mark"] = {"layout": "group"}
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": ds, "fields": fields,
                                                                                  "disaggregated": False}}], "spec": spec},
            "position": pos}


def line(name, ds, title, pos):
    fields = [{"name": "monthly(month)", "expression": 'DATE_TRUNC("MONTH", `month`)'},
              {"name": "sum(value)", "expression": "SUM(`value`)"}, {"name": "series", "expression": "`series`"}]
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": ds, "fields": fields, "disaggregated": False}}],
                       "spec": {"version": 3, "widgetType": "line", "encodings": {
                           "x": {"fieldName": "monthly(month)", "scale": {"type": "temporal"}, "displayName": "Month"},
                           "y": {"fieldName": "sum(value)", "scale": {"type": "quantitative"}, "displayName": "Inventory value (USD)", "format": USD},
                           "color": {"fieldName": "series", "scale": {"type": "categorical"}, "displayName": "Series"}},
                           "frame": {"showTitle": True, "title": title}}}, "position": pos}


def table(name, ds, cols, title, pos):
    fields = [{"name": c, "expression": f"`{c}`"} for c, _ in cols]
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": ds, "fields": fields, "disaggregated": True}}],
                       "spec": {"version": 2, "widgetType": "table",
                                "encodings": {"columns": [{"fieldName": c, "displayName": d} for c, d in cols]},
                                "frame": {"showTitle": True, "title": title}}}, "position": pos}


def filt(name, field, title, dss, y, wtype="filter-multi-select"):
    qs = [{"name": f"{name}_{d}", "query": {"datasetName": d, "fields": [{"name": field, "expression": f"`{field}`"}], "disaggregated": False}}
          for d in dss]
    return {"widget": {"name": name, "queries": qs, "spec": {"version": 2, "widgetType": wtype, "encodings": {"fields": [
        {"fieldName": field, "displayName": title, "queryName": q["name"]} for q in qs]}, "frame": {"showTitle": True, "title": title}}},
        "position": {"x": 0, "y": y, "width": 2, "height": 2}}


def build(g):
    ds = datasets(g)
    allf = ["ds_metrics", "ds_exposure", "ds_monthly", "ds_returns", "ds_expiry", "ds_queue"]
    page = []
    page.append(text("title", "## RNI Executive Inventory Intelligence", 0, 0, 6, 1))
    page.append(text("subtitle", "FFF Enterprises · Right Now Inventory · **synthetic demo data** — values are illustrative; "
                                 "exposure is potential, not realized savings. Risk buckets are mutually exclusive.", 0, 1, 6, 1))
    kp = [("kpi_inventory", "inventory_value", "Total inventory deployed"),
          ("kpi_excess", "potential_excess_exposure_value", "Potential excess exposure"),
          ("kpi_expiry", "near_expiry_value", "Approaching expiration (≤90d)"),
          ("kpi_review", "requests_requiring_review", "Requests requiring review"),
          ("kpi_returns", "returned_value", "Returns value (12 mo)"),
          ("kpi_logistics", "avoidable_logistics_cost_12m", "Est. avoidable logistics (12 mo)")]
    for i, (n, f, t) in enumerate(kp):
        page.append(counter(n, "ds_metrics", f, t, i, 2, fmt=(f != "requests_requiring_review")))
    page.append(bar("exp_region", "ds_exposure", "region", "value", "bucket", "Inventory exposure by region",
                    {"x": 0, "y": 5, "width": 3, "height": 6}))
    page.append(bar("exp_category", "ds_exposure", "product_category", "value", "bucket", "Inventory exposure by product category",
                    {"x": 3, "y": 5, "width": 3, "height": 6}, horizontal=True))
    page.append(line("cons_vs_ship", "ds_monthly", "Historical consumption vs shipments", {"x": 0, "y": 11, "width": 3, "height": 6}))
    page.append(bar("returns_trend", "ds_returns", "return_month", "returned_value", "return_type",
                    "Return trends — last 12 months", {"x": 3, "y": 11, "width": 3, "height": 6}, x_date=True))
    page.append(bar("top10", "ds_top10", "customer_name", "potential_excess_exposure", None,
                    "Top 10 locations by potential excess inventory", {"x": 0, "y": 17, "width": 3, "height": 6}, horizontal=True))
    page.append(bar("expiry_horizon", "ds_expiry", "expiry_horizon", "inventory_value", None,
                    "Expiration risk by time horizon", {"x": 3, "y": 17, "width": 3, "height": 6}))
    page.append(table("review_table", "ds_queue", [
        ("review_priority", "Priority"), ("customer_name", "Customer"), ("product_name", "Product"),
        ("requested_qty", "Requested"), ("recommended_qty", "Engine rec."), ("on_hand_qty", "On hand"),
        ("par_level", "PAR"), ("consumed_last_120d", "Used 120d"), ("risk_category", "Risk"),
        ("potential_exposure_value", "Potential exposure $"), ("review_reason", "Why flagged")],
        "High-priority shipment requests for review", {"x": 0, "y": 23, "width": 6, "height": 8}))
    filters = [
        filt("f_region", "region", "Region", allf, 0),
        filt("f_customer", "customer_name", "Customer", allf, 2),
        filt("f_category", "product_category", "Product category", allf, 4),
        filt("f_product", "product_name", "Product", allf, 6),
        filt("f_month", "month", "Month (consumption vs shipments)", ["ds_monthly"], 8, "filter-date-range-picker"),
        filt("f_return_month", "return_month", "Return month", ["ds_returns"], 10, "filter-date-range-picker"),
    ]
    return {
        "datasets": [{"name": k, "displayName": k.replace("ds_", "").replace("_", " ").title(), "queryLines": [v]} for k, v in ds.items()],
        "pages": [{"name": "overview", "displayName": "Executive overview", "pageType": "PAGE_TYPE_CANVAS", "layout": page},
                  {"name": "filters", "displayName": "Filters", "pageType": "PAGE_TYPE_GLOBAL_FILTERS", "layout": filters}],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", default="rni_demo")
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--dashboard-id", default=None)
    a = p.parse_args()
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    g = f"{a.catalog}.gold"
    for k, sql in datasets(g).items():
        df = run(w, a.warehouse_id, f"SELECT * FROM ({sql}) LIMIT 5")
        assert len(df), f"dataset {k} returned no rows"
        print(f"tested {k}: columns {list(df.columns)}")
    body = build(g)
    (ROOT / "dashboards").mkdir(exist_ok=True)
    (ROOT / "dashboards" / "rni_executive_inventory_intelligence.lvdash.json").write_text(json.dumps(body, indent=2))
    me = w.current_user.me().user_name
    payload = {"display_name": TITLE, "warehouse_id": a.warehouse_id, "serialized_dashboard": json.dumps(body),
               "parent_path": f"/Workspace/Users/{me}"}
    dash_id = a.dashboard_id
    if not dash_id:
        for d in w.api_client.do("GET", "/api/2.0/lakeview/dashboards", query={"page_size": 200}).get("dashboards", []):
            if d.get("display_name") == TITLE and d.get("lifecycle_state") != "TRASHED":
                dash_id = d["dashboard_id"]
    if dash_id:
        w.api_client.do("PATCH", f"/api/2.0/lakeview/dashboards/{dash_id}",
                        body={k: v for k, v in payload.items() if k != "parent_path"})
    else:
        dash_id = w.api_client.do("POST", "/api/2.0/lakeview/dashboards", body=payload)["dashboard_id"]
    w.api_client.do("POST", f"/api/2.0/lakeview/dashboards/{dash_id}/published",
                    body={"embed_credentials": True, "warehouse_id": a.warehouse_id})
    (ROOT / "config" / "dashboard_id.txt").write_text(dash_id + "\n")
    print("DASHBOARD_ID", dash_id)
    print(f"URL {w.config.host}/dashboardsv3/{dash_id}/published")


if __name__ == "__main__":
    main()

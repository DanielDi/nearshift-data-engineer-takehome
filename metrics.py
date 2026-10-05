"""Pure read-only metric service shared by HTTP, MCP and the assistant."""
from __future__ import annotations
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "nearshift.duckdb"
MONTH_PATTERN = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])\Z")
METRIC_DEFINITION = (
    "Sum of item prices for delivered orders, assigned to purchase month; "
    "excludes freight and unobserved refunds. This is a revenue proxy, "
    "not accounting revenue."
)


def query_month(database_path: Path, month: date | None) -> dict | None:
    """Read only the curated monthly mart; None selects the latest month with sales."""
    db = duckdb.connect(str(database_path), read_only=True)
    try:
        if month is None:
            row = db.execute(
                """SELECT purchase_month, merchandise_value, delivered_orders,
                          in_trend_window
                   FROM analytics.mart_monthly_metrics
                   WHERE delivered_orders > 0
                   ORDER BY purchase_month DESC LIMIT 1"""
            ).fetchone()
        else:
            row = db.execute(
                """SELECT purchase_month, merchandise_value, delivered_orders,
                          in_trend_window
                   FROM analytics.mart_monthly_metrics
                   WHERE purchase_month = ?""",
                [month],
            ).fetchone()
        if row is None:
            return None
        latest_source_date = db.execute(
            "SELECT CAST(MAX(purchased_at) AS DATE) FROM analytics.fact_order"
        ).fetchone()[0]
    finally:
        db.close()

    purchase_month, amount, order_count, in_trend_window = row
    return {
        "metric": "delivered_merchandise_value",
        "month": purchase_month.strftime("%Y-%m"),
        "value": format(Decimal(amount), ".2f"),
        "currency": "BRL",
        "delivered_orders": int(order_count),
        "definition": METRIC_DEFINITION,
        "source_table": "analytics.mart_monthly_metrics",
        "in_trend_window": bool(in_trend_window),
        "latest_source_purchase_date": latest_source_date.isoformat(),
        "coverage_note": (
            "Historical snapshot; this is not a current-month business metric."
            if in_trend_window
            else "Sparse source boundary month; interpret the value with caution."
        ),
    }


METRICS = {
    "monthly_revenue",
    "monthly_aov",
    "repeat_purchase_rate",
    "top_categories",
    "late_delivery_rate",
    "unsupported",
}

def query_metric(database_path: Path, metric: str, month: str | None) -> dict:
    """Execute one of five fixed queries; never interpolate model text into SQL."""
    if metric not in METRICS:
        raise ValueError("Metric is not allowed.")
    if metric == "unsupported":
        return {"status": "unsupported"}
    if metric in {"monthly_revenue", "monthly_aov"}:
        if month is None:
            return {"status": "month_required"}
        if month != "latest" and not MONTH_PATTERN.fullmatch(month):
            raise ValueError("Invalid month.")
        selected_month = None if month == "latest" else date.fromisoformat(month + "-01")
        if metric == "monthly_revenue":
            row = query_month(database_path, selected_month)
            return {"status": "ok", **row} if row else {"status": "month_unavailable", "month": month}
        db = duckdb.connect(str(database_path), read_only=True)
        try:
            if selected_month is None:
                row = db.execute(
                    """SELECT purchase_month, average_order_value, delivered_orders,
                              in_trend_window
                       FROM analytics.mart_monthly_metrics
                       WHERE delivered_orders > 0
                       ORDER BY purchase_month DESC LIMIT 1"""
                ).fetchone()
            else:
                row = db.execute(
                    """SELECT purchase_month, average_order_value, delivered_orders,
                              in_trend_window
                       FROM analytics.mart_monthly_metrics
                       WHERE purchase_month = ?""", [selected_month]
                ).fetchone()
        finally:
            db.close()
        if not row or row[1] is None:
            return {"status": "month_unavailable", "month": month}
        return {
            "status": "ok", "metric": metric, "month": row[0].strftime("%Y-%m"),
            "value": format(Decimal(row[1]), ".2f"), "currency": "BRL",
            "delivered_orders": int(row[2]), "in_trend_window": bool(row[3]),
            "source_table": "analytics.mart_monthly_metrics",
        }
    if month is not None:
        return {"status": "unsupported"}
    db = duckdb.connect(str(database_path), read_only=True)
    try:
        if metric == "repeat_purchase_rate":
            repeat_count, customer_count = db.execute(
                """SELECT COUNT(*) FILTER (WHERE is_repeat_customer), COUNT(*)
                   FROM analytics.mart_customer_repeat"""
            ).fetchone()
            return {
                "status": "ok", "metric": metric, "repeat_customers": repeat_count,
                "delivered_customers": customer_count,
                "rate_percent": round(100 * repeat_count / customer_count, 2)
                if customer_count else None,
                "source_table": "analytics.mart_customer_repeat",
            }
        if metric == "top_categories":
            rows = db.execute(
                """SELECT category_name, merchandise_value
                   FROM analytics.mart_category_metrics
                   ORDER BY merchandise_value DESC, category_name ASC LIMIT 5"""
            ).fetchall()
            return {
                "status": "ok", "metric": metric, "currency": "BRL",
                "categories": [
                    {"category": name, "merchandise_value": format(Decimal(value), ".2f")}
                    for name, value in rows
                ],
                "source_table": "analytics.mart_category_metrics",
            }
        late_orders, comparable_orders = db.execute(
            """SELECT COUNT(*) FILTER (WHERE is_late), COUNT(*)
               FROM analytics.mart_delivery"""
        ).fetchone()
        return {
            "status": "ok", "metric": metric, "late_orders": late_orders,
            "comparable_delivered_orders": comparable_orders,
            "rate_percent": round(100 * late_orders / comparable_orders, 2)
            if comparable_orders else None,
            "source_table": "analytics.mart_delivery",
        }
    finally:
        db.close()

"""Build a standalone, source-backed demo page from curated Olist outputs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parent


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_data(database_path: Path, report_dir: Path) -> dict:
    monthly = [
        {
            "month": row["purchase_month"][:7],
            "value": float(row["merchandise_value"]),
            "orders": int(row["delivered_orders"]),
            "aov": float(row["average_order_value"]),
            "repeat_rate": float(row["monthly_repeat_customer_rate"]),
        }
        for row in read_rows(report_dir / "monthly_metrics.csv")
        if row["in_trend_window"].lower() == "true" and int(row["delivered_orders"]) > 0
    ]
    monthly.sort(key=lambda row: row["month"])
    categories = [
        {"name": row["category_name"], "value": float(row["merchandise_value"])}
        for row in read_rows(report_dir / "category_metrics.csv")
    ]
    categories.sort(key=lambda row: (-row["value"], row["name"]))
    db = duckdb.connect(str(database_path), read_only=True)
    try:
        value, orders = db.execute(
            """SELECT SUM(item_subtotal), COUNT(*) FROM analytics.mart_order
               WHERE order_status = 'delivered'"""
        ).fetchone()
        repeat_count, customers = db.execute(
            """SELECT COUNT(*) FILTER (WHERE is_repeat_customer), COUNT(*)
               FROM analytics.mart_customer_repeat"""
        ).fetchone()
        late_count, comparable = db.execute(
            """SELECT COUNT(*) FILTER (WHERE is_late), COUNT(*)
               FROM analytics.mart_delivery"""
        ).fetchone()
        latest_source_date = db.execute(
            "SELECT CAST(MAX(purchased_at) AS DATE) FROM analytics.fact_order"
        ).fetchone()[0]
    finally:
        db.close()
    if not monthly or not categories or not orders or not customers or not comparable:
        raise ValueError("Curated data is incomplete; run python run.py first.")
    return {
        "source": "Olist Brazilian E-Commerce Public Dataset, version 2",
        "source_date": latest_source_date.isoformat(),
        "months": monthly,
        "categories": categories[:8],
        "overall": {
            "value": float(value), "orders": orders,
            "aov": float(value / orders),
            "repeat_customers": repeat_count, "customers": customers,
            "repeat_rate": 100 * repeat_count / customers,
            "late_orders": late_count, "comparable_orders": comparable,
            "late_rate": 100 * late_count / comparable,
        },
    }


def build_showcase(database_path: Path, report_dir: Path,
                   output_path: Path = ROOT / "showcase" / "index.html") -> Path:
    data = build_data(database_path, report_dir)
    template = (ROOT / "showcase" / "template.html").read_text(encoding="utf-8")
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template.replace("__DATA_JSON__", serialized), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "nearshift.duckdb")
    parser.add_argument("--reports", type=Path, default=ROOT / "reports")
    parser.add_argument("--output", type=Path, default=ROOT / "showcase" / "index.html")
    args = parser.parse_args()
    print(build_showcase(args.db, args.reports, args.output))


if __name__ == "__main__":
    main()

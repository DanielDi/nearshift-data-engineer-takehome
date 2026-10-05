"""Build the Olist raw, analytics and reporting layers end to end."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parent
DATASET_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "olistbr/brazilian-ecommerce?datasetVersionNumber=2"
)
SOURCE_PAGE = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"
FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def ensure_raw_files(data_dir: Path, offline: bool) -> Path:
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    missing = [name for name in FILES.values() if not (raw_dir / name).is_file()]
    if not missing:
        print("Using existing raw CSV files")
        return raw_dir
    if offline:
        raise RuntimeError(f"Missing raw files in offline mode: {', '.join(missing)}")

    archive = data_dir / "olist-v2.zip"
    if not archive.is_file():
        temporary = archive.with_suffix(".zip.part")
        print("Downloading Olist dataset version 2 from Kaggle...")
        request = urllib.request.Request(DATASET_URL, headers={"User-Agent": "NearShift-takehome/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
        except urllib.error.URLError:
            # Some managed environments expose network access only through curl.
            if not shutil.which("curl"):
                raise
            temporary.unlink(missing_ok=True)
            subprocess.run(
                ["curl", "--location", "--fail", "--silent", "--show-error",
                 DATASET_URL, "--output", str(temporary)],
                check=True,
            )
        temporary.replace(archive)

    print("Extracting selected source CSVs...")
    with zipfile.ZipFile(archive) as bundle:
        available = set(bundle.namelist())
        missing_from_archive = set(FILES.values()) - available
        if missing_from_archive:
            raise RuntimeError(f"Source archive lacks: {sorted(missing_from_archive)}")
        for name in FILES.values():
            destination = raw_dir / name
            if destination.is_file():
                continue
            with bundle.open(name) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)

    sha256 = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha256.update(block)
    manifest = {
        "source": SOURCE_PAGE,
        "download_url": DATASET_URL,
        "dataset_version": 2,
        "archive_sha256": sha256.hexdigest(),
        "extracted_files": list(FILES.values()),
    }
    (data_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return raw_dir


def load_raw(db: duckdb.DuckDBPyConnection, raw_dir: Path) -> None:
    db.execute("CREATE SCHEMA IF NOT EXISTS raw")
    for table, filename in FILES.items():
        path_literal = raw_dir.joinpath(filename).as_posix().replace("'", "''")
        db.execute(
            f"CREATE OR REPLACE TABLE raw.{table} AS "
            f"SELECT * FROM read_csv('{path_literal}', all_varchar=true, header=true)"
        )
        count = db.execute(f"SELECT COUNT(*) FROM raw.{table}").fetchone()[0]
        print(f"Loaded raw.{table}: {count:,} rows")


def scalar(db: duckdb.DuckDBPyConnection, query: str):
    return db.execute(query).fetchone()[0]


def run_checks(db: duckdb.DuckDBPyConnection) -> list[dict]:
    """Expected-zero checks. Payment discrepancies are reported, not hidden."""
    checks = {
        "order row count": "SELECT (SELECT COUNT(*) FROM raw.orders) - (SELECT COUNT(*) FROM analytics.fact_order)",
        "item row count": "SELECT (SELECT COUNT(*) FROM raw.order_items) - (SELECT COUNT(*) FROM analytics.fact_order_item)",
        "payment row count": "SELECT (SELECT COUNT(*) FROM raw.order_payments) - (SELECT COUNT(*) FROM analytics.fact_payment)",
        "product row count": "SELECT (SELECT COUNT(*) FROM raw.products) - (SELECT COUNT(*) FROM analytics.dim_product)",
        "customer identity count": "SELECT (SELECT COUNT(DISTINCT customer_unique_id) FROM raw.customers) - (SELECT COUNT(*) FROM analytics.dim_customer)",
        "mart order row count": "SELECT (SELECT COUNT(*) FROM raw.orders) - (SELECT COUNT(*) FROM analytics.mart_order)",
        "duplicate order IDs": "SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM raw.orders",
        "null order IDs": "SELECT COUNT(*) FROM raw.orders WHERE order_id IS NULL",
        "duplicate item keys": "SELECT COUNT(*) FROM (SELECT order_id, order_item_id FROM raw.order_items GROUP BY 1, 2 HAVING COUNT(*) > 1)",
        "duplicate payment keys": "SELECT COUNT(*) FROM (SELECT order_id, payment_sequential FROM raw.order_payments GROUP BY 1, 2 HAVING COUNT(*) > 1)",
        "items without orders": "SELECT COUNT(*) FROM raw.order_items i LEFT JOIN raw.orders o USING (order_id) WHERE o.order_id IS NULL",
        "payments without orders": "SELECT COUNT(*) FROM raw.order_payments p LEFT JOIN raw.orders o USING (order_id) WHERE o.order_id IS NULL",
        "orders without customers": "SELECT COUNT(*) FROM raw.orders o LEFT JOIN raw.customers c USING (customer_id) WHERE c.customer_id IS NULL",
        "items without products": "SELECT COUNT(*) FROM raw.order_items i LEFT JOIN raw.products p USING (product_id) WHERE p.product_id IS NULL",
        "invalid item prices": "SELECT COUNT(*) FROM analytics.fact_order_item WHERE item_price IS NULL OR item_price < 0 OR freight_value IS NULL OR freight_value < 0",
        "invalid payment values": "SELECT COUNT(*) FROM analytics.fact_payment WHERE payment_value IS NULL OR payment_value < 0",
        "invalid purchase timestamps": "SELECT COUNT(*) FROM analytics.fact_order WHERE purchased_at IS NULL",
        "raw item price difference (cents)": "SELECT CAST(ROUND(100 * ((SELECT SUM(TRY_CAST(price AS DECIMAL(18,2))) FROM raw.order_items) - (SELECT SUM(item_price) FROM analytics.fact_order_item))) AS BIGINT)",
        "raw freight difference (cents)": "SELECT CAST(ROUND(100 * ((SELECT SUM(TRY_CAST(freight_value AS DECIMAL(18,2))) FROM raw.order_items) - (SELECT SUM(freight_value) FROM analytics.fact_order_item))) AS BIGINT)",
        "raw payment difference (cents)": "SELECT CAST(ROUND(100 * ((SELECT SUM(TRY_CAST(payment_value AS DECIMAL(18,2))) FROM raw.order_payments) - (SELECT SUM(payment_value) FROM analytics.fact_payment))) AS BIGINT)",
        "order item subtotal differences": "WITH source AS (SELECT order_id, SUM(TRY_CAST(price AS DECIMAL(18,2))) amount FROM raw.order_items GROUP BY 1) SELECT COUNT(*) FROM source s JOIN analytics.mart_order m USING (order_id) WHERE s.amount <> m.item_subtotal",
        "order payment total differences": "WITH source AS (SELECT order_id, SUM(TRY_CAST(payment_value AS DECIMAL(18,2))) amount FROM raw.order_payments GROUP BY 1) SELECT COUNT(*) FROM source s JOIN analytics.mart_order m USING (order_id) WHERE s.amount <> m.payment_total",
        "raw delivered merchandise difference (cents)": "SELECT CAST(ROUND(100 * ((SELECT SUM(TRY_CAST(i.price AS DECIMAL(18,2))) FROM raw.order_items i JOIN raw.orders o USING (order_id) WHERE o.order_status = 'delivered') - (SELECT SUM(item_subtotal) FROM analytics.mart_order WHERE order_status = 'delivered'))) AS BIGINT)",
        "category total difference (cents)": "SELECT CAST(ROUND(100 * ((SELECT COALESCE(SUM(merchandise_value), 0) FROM analytics.mart_category_metrics) - (SELECT COALESCE(SUM(i.item_price), 0) FROM analytics.fact_order_item i JOIN analytics.fact_order o USING (order_id) WHERE o.order_status = 'delivered'))) AS BIGINT)",
        "monthly total difference (cents)": "SELECT CAST(ROUND(100 * ((SELECT COALESCE(SUM(merchandise_value), 0) FROM analytics.mart_monthly_metrics) - (SELECT COALESCE(SUM(item_subtotal), 0) FROM analytics.mart_order WHERE order_status = 'delivered'))) AS BIGINT)",
    }
    result = []
    for name, query in checks.items():
        actual = scalar(db, query)
        result.append({"check": name, "actual": int(actual), "passed": actual == 0})
    return result


def records(db: duckdb.DuckDBPyConnection, query: str) -> list[dict]:
    result = db.execute(query)
    names = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def money(value) -> str:
    return f"R$ {value:,.2f}"


def plot_monthly(rows: list[dict], path: Path) -> None:
    months = [row["purchase_month"].strftime("%Y-%m") for row in rows]
    values = [float(row["merchandise_value"]) / 1_000_000 for row in rows]
    fig, ax = plt.subplots(figsize=(11, 4.6), layout="constrained")
    ax.plot(months, values, color="#155e75", linewidth=2.5, marker="o", markersize=4)
    ax.set_title("Delivered merchandise value by purchase month", loc="left", weight="bold")
    ax.set_ylabel("R$ million")
    ax.grid(axis="y", color="#d9e2e7")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", rotation=55)
    ax.set_ylim(bottom=0)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_aov(rows: list[dict], path: Path) -> None:
    months = [row["purchase_month"].strftime("%Y-%m") for row in rows]
    values = [float(row["average_order_value"]) for row in rows]
    fig, ax = plt.subplots(figsize=(11, 4.6), layout="constrained")
    ax.plot(months, values, color="#9a3412", linewidth=2.5, marker="o", markersize=4)
    ax.set_title("Average order value by purchase month", loc="left", weight="bold")
    ax.set_ylabel("R$ per delivered order")
    ax.grid(axis="y", color="#d9e2e7")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", rotation=55)
    ax.set_ylim(min(values) - 8, max(values) + 8)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_categories(rows: list[dict], path: Path) -> None:
    top = list(reversed(rows[:10]))
    labels = [row["category_name"].replace("_", " ") for row in top]
    values = [float(row["merchandise_value"]) / 1_000_000 for row in top]
    fig, ax = plt.subplots(figsize=(10, 5.6), layout="constrained")
    ax.barh(labels, values, color="#155e75")
    ax.set_title("Top categories by delivered merchandise value", loc="left", weight="bold")
    ax.set_xlabel("R$ million")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.1f}"))
    ax.grid(axis="x", color="#d9e2e7")
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def write_reports(db: duckdb.DuckDBPyConnection, checks: list[dict], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    monthly_all = records(db, "SELECT * FROM analytics.mart_monthly_metrics ORDER BY purchase_month")
    monthly = [row for row in monthly_all if row["in_trend_window"]]
    categories = records(db, "SELECT * FROM analytics.mart_category_metrics ORDER BY merchandise_value DESC")
    write_csv(report_dir / "monthly_metrics.csv", monthly_all)
    write_csv(report_dir / "category_metrics.csv", categories)
    plot_monthly(monthly, report_dir / "monthly_merchandise_value.png")
    plot_aov(monthly, report_dir / "monthly_aov.png")
    plot_categories(categories, report_dir / "top_categories.png")

    source_counts = records(db, """
        SELECT 'orders' AS source_table, COUNT(*) AS rows FROM raw.orders
        UNION ALL SELECT 'order_items', COUNT(*) FROM raw.order_items
        UNION ALL SELECT 'order_payments', COUNT(*) FROM raw.order_payments
        UNION ALL SELECT 'order_reviews', COUNT(*) FROM raw.order_reviews
        UNION ALL SELECT 'customers', COUNT(*) FROM raw.customers
        UNION ALL SELECT 'products', COUNT(*) FROM raw.products
        UNION ALL SELECT 'category_translation', COUNT(*) FROM raw.category_translation
    """)
    status = records(db, """
        SELECT order_status, COUNT(*) AS orders,
            SUM(item_subtotal) AS item_subtotal,
            SUM(freight_total) AS freight_total,
            SUM(payment_total) AS payment_total,
            COUNT(*) FILTER (WHERE item_rows = 0) AS orders_without_items,
            COUNT(*) FILTER (WHERE payment_rows = 0) AS orders_without_payment,
            COUNT(*) FILTER (WHERE item_rows > 0 AND payment_rows > 0
                AND ABS(payment_total - item_subtotal - freight_total) > 0.01)
                AS payment_mismatches
        FROM analytics.mart_order GROUP BY 1 ORDER BY orders DESC
    """)
    write_csv(report_dir / "order_status_reconciliation.csv", status)
    exceptions = records(db, """
        SELECT order_id, order_status, item_subtotal, freight_total,
            payment_total, payment_total - item_subtotal - freight_total AS difference
        FROM analytics.mart_order
        WHERE item_rows > 0 AND payment_rows > 0
          AND ABS(payment_total - item_subtotal - freight_total) > 0.01
        ORDER BY ABS(difference) DESC
    """)
    write_csv(report_dir / "payment_exceptions.csv", exceptions)

    delivered = next(row for row in status if row["order_status"] == "delivered")
    repeat = records(db, """
        SELECT COUNT(*) AS customers,
            COUNT(*) FILTER (WHERE is_repeat_customer) AS repeat_customers
        FROM analytics.mart_customer_repeat
    """)[0]
    delivery = records(db, """
        SELECT COUNT(*) AS measured_deliveries,
            COUNT(*) FILTER (WHERE is_late) AS late_deliveries
        FROM analytics.mart_delivery
    """)[0]
    category_missing = scalar(db, """
        SELECT COUNT(*) FROM analytics.dim_product WHERE category_name = 'uncategorized'
    """)
    category_untranslated = scalar(db, """
        SELECT COUNT(*) FROM raw.products p
        LEFT JOIN raw.category_translation t
          ON p.product_category_name = t.product_category_name
        WHERE p.product_category_name IS NOT NULL
          AND t.product_category_name IS NULL
    """)
    delivered_missing_date = scalar(db, """
        SELECT COUNT(*) FROM analytics.fact_order
        WHERE order_status = 'delivered' AND delivered_to_customer_at IS NULL
    """)
    total_value = scalar(db, """
        SELECT SUM(item_subtotal) FROM analytics.mart_order WHERE order_status = 'delivered'
    """)
    aov = total_value / delivered["orders"]
    top = categories[:5]
    aov_low = min(monthly, key=lambda row: row["average_order_value"])
    aov_high = max(monthly, key=lambda row: row["average_order_value"])
    peak_month = max(monthly, key=lambda row: row["merchandise_value"])

    insight_lines = [
        "# Olist analytics findings",
        "",
        f"Source: [Olist Brazilian E-Commerce, version 2]({SOURCE_PAGE}).",
        "The data is historical (2016–2018), so these are dataset findings rather than current business results.",
        "",
        "## Metric definitions",
        "",
        "- **Delivered merchandise value (revenue proxy):** sum of item `price` for orders with status `delivered`; excludes freight, tax and unobserved refunds. Currency: BRL.",
        "- **Average order value (AOV):** delivered merchandise value / delivered orders, assigned to purchase month.",
        "- **Lifetime repeat-purchase rate:** customers (`customer_unique_id`) with at least two delivered orders / customers with at least one delivered order.",
        "- **Monthly repeat-buyer rate:** buyers active that month who have a previous delivered order / all buyers active that month. Prior orders can precede the displayed window.",
        "- **Late-delivery rate:** delivered orders whose actual delivery calendar date is after the estimated calendar date / delivered orders with both dates.",
        "",
        "## Results",
        "",
        f"- Delivered merchandise value across all source dates: **{money(total_value)}** from **{delivered['orders']:,}** delivered orders; overall AOV **{money(aov)}**.",
        f"- In the displayed months, delivered merchandise value peaked in **{peak_month['purchase_month']:%B %Y} ({money(peak_month['merchandise_value'])})**.",
        f"- Monthly AOV varied from **{money(aov_low['average_order_value'])} ({aov_low['purchase_month']:%B %Y})** to **{money(aov_high['average_order_value'])} ({aov_high['purchase_month']:%B %Y})**; it was {money(monthly[0]['average_order_value'])} in the first displayed month and {money(monthly[-1]['average_order_value'])} in the last.",
        f"- Lifetime repeat-purchase rate: **{repeat['repeat_customers']:,} / {repeat['customers']:,} = {repeat['repeat_customers'] / repeat['customers']:.2%}**.",
        f"- Late-delivery rate: **{delivery['late_deliveries']:,} / {delivery['measured_deliveries']:,} = {delivery['late_deliveries'] / delivery['measured_deliveries']:.2%}**.",
        f"- Top category by delivered merchandise value: **{top[0]['category_name']} ({money(top[0]['merchandise_value'])})**.",
        f"- **{category_missing:,}** products lack an original category and are retained as `uncategorized`.",
        "",
        "| Top category | Delivered merchandise value |",
        "|---|---:|",
    ]
    insight_lines.extend(f"| {row['category_name']} | {money(row['merchandise_value'])} |" for row in top)
    insight_lines += [
        "",
        "## Trends and scope",
        "",
        "The monthly charts cover January 2017 through August 2018. The sparse boundary months remain in the raw, modeled and monthly mart tables; `monthly_metrics.csv` includes them with `in_trend_window = false`.",
        "",
        "![Monthly merchandise value](monthly_merchandise_value.png)",
        "",
        "![Monthly average order value](monthly_aov.png)",
        "",
        "![Top categories](top_categories.png)",
        "",
        "See `monthly_metrics.csv` and `category_metrics.csv` for the underlying values.",
        "",
    ]
    (report_dir / "INSIGHTS.md").write_text("\n".join(insight_lines), encoding="utf-8")

    validation_lines = [
        "# Validation and reconciliation",
        "",
        "Original CSV files remain unchanged. Source columns are loaded as strings (blank cells become SQL NULL); typed analytics tables are checked against them.",
        "",
        "## Raw row counts",
        "",
        "| Table | Rows |",
        "|---|---:|",
    ]
    validation_lines.extend(f"| {row['source_table']} | {row['rows']:,} |" for row in source_counts)
    validation_lines += ["", "## Automated checks", "", "| Check | Result | Observed difference/count |", "|---|---|---:|"]
    validation_lines.extend(
        f"| {row['check']} | {'PASS' if row['passed'] else 'FAIL'} | {row['actual']:,} |"
        for row in checks
    )
    validation_lines += [
        "",
        "## Payment versus item and freight totals",
        "",
        "Payment and merchandise value are different measures. Payments can occur on canceled or unavailable orders. Do not force their totals to match.",
        "",
        "| Status | Orders | Item value | Freight | Payments | No items | No payment | Mismatch orders |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    validation_lines.extend(
        f"| {row['order_status']} | {row['orders']:,} | {money(row['item_subtotal'])} | "
        f"{money(row['freight_total'])} | {money(row['payment_total'])} | "
        f"{row['orders_without_items']:,} | {row['orders_without_payment']:,} | "
        f"{row['payment_mismatches']:,} |"
        for row in status
    )
    validation_lines += [
        "",
        f"There are **{len(exceptions):,}** orders with both items and payments whose totals differ by more than R$0.01; see `payment_exceptions.csv` for the order-level reconciliation.",
        f"Missingness retained in the model: **{category_missing:,}** products have no category, **{category_untranslated:,}** categorized products have no English translation, and **{delivered_missing_date:,}** delivered orders have no actual delivery date.",
        "The dataset does not provide a reliable refund ledger, so payment discrepancies are exposed rather than imputed.",
        "Source timestamps have no documented time-zone offset; they are treated as local, naive timestamps without conversion.",
        "",
    ]
    (report_dir / "VALIDATION.md").write_text("\n".join(validation_lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Use existing data/raw CSVs only")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = ensure_raw_files(args.data_dir, args.offline)
    db_path = args.data_dir / "nearshift.duckdb"
    db = duckdb.connect(str(db_path))
    try:
        load_raw(db, raw_dir)
        print("Building analytics tables and marts...")
        db.execute((ROOT / "sql" / "model.sql").read_text(encoding="utf-8"))
        print("Running validation checks...")
        checks = run_checks(db)
        write_reports(db, checks, args.report_dir)
    finally:
        db.close()
    failed = [check for check in checks if not check["passed"]]
    if not failed:
        from build_showcase import build_showcase
        showcase_path = build_showcase(db_path, args.report_dir)
        print(f"Showcase: {showcase_path.resolve()}")
    print(f"Validation: {len(checks) - len(failed)}/{len(checks)} checks passed")
    print(f"Reports: {args.report_dir.resolve()}")
    print(f"Database: {db_path.resolve()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

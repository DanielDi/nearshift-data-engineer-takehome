"""Build, validate, then package a minimal aggregate-only serving database."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from metrics import query_metric


def compact_database(source: Path, output: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    if source == output or output.exists():
        raise ValueError("Serving output must be a new file, different from the pipeline database.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(output)) as db:
        db.execute("SET memory_limit='256MB'")
        # ATTACH cannot use bind parameters; this is a validated operator path.
        source_literal = source.as_posix().replace("'", "''")
        db.execute(f"ATTACH '{source_literal}' AS full_model (READ_ONLY)")
        db.execute("CREATE SCHEMA analytics")
        for table in ("mart_monthly_metrics", "mart_category_metrics"):
            db.execute(f"CREATE TABLE analytics.{table} AS SELECT * FROM full_model.analytics.{table}")
        # One flag per eligible row retains the exact approved denominators; no IDs.
        db.execute("CREATE TABLE analytics.mart_customer_repeat AS SELECT is_repeat_customer FROM full_model.analytics.mart_customer_repeat")
        db.execute("CREATE TABLE analytics.mart_delivery AS SELECT is_late FROM full_model.analytics.mart_delivery")
        db.execute("CREATE TABLE analytics.fact_order AS SELECT MAX(purchased_at) purchased_at FROM full_model.analytics.fact_order")
    for metric, month in (("monthly_revenue", "2017-11"), ("monthly_revenue", "latest"),
                          ("monthly_aov", "latest"), ("repeat_purchase_rate", None),
                          ("top_categories", None), ("late_delivery_rate", None)):
        if query_metric(source, metric, month) != query_metric(output, metric, month):
            raise ValueError(f"Serving result does not match the pipeline for {metric}.")
    print(f"Serving database validated: {output.stat().st_size:,} bytes; no customer or order identifiers")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-db", type=Path, help="Validate packaging against a local completed pipeline")
    args = parser.parse_args()
    source = args.existing_db or ROOT / "data" / "render-build" / "nearshift.duckdb"
    if not args.existing_db:
        subprocess.run([sys.executable, str(ROOT / "run.py"), "--data-dir", str(source.parent),
                        "--memory-limit", "256MB"], cwd=ROOT, check=True)
    target = ROOT / "data" / "serving.duckdb"
    # Replace only this named, generated artifact; the source database stays intact.
    target.unlink(missing_ok=True)
    compact_database(source, target)
    from build_showcase import build_showcase
    build_showcase(source, ROOT / "reports")
    manifest = {"source": "Olist v2", "scope": "aggregate-only serving snapshot", "tables": 5}
    (ROOT / "data" / "serving_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

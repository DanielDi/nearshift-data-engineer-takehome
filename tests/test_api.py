"""HTTP behavior and guardrails for the read-only metric API."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import duckdb

from api import create_server


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.database = Path(cls.temporary.name) / "fixture.duckdb"
        db = duckdb.connect(str(cls.database))
        db.execute("CREATE SCHEMA analytics")
        db.execute("""
            CREATE TABLE analytics.mart_monthly_metrics (
                purchase_month DATE, merchandise_value DECIMAL(18,2),
                delivered_orders BIGINT, in_trend_window BOOLEAN
            )
        """)
        db.execute("""
            INSERT INTO analytics.mart_monthly_metrics VALUES
                (DATE '2017-11-01', 987765.37, 7289, true),
                (DATE '2018-09-01', 0.00, 0, false)
        """)
        db.execute("CREATE TABLE analytics.fact_order (purchased_at TIMESTAMP)")
        db.execute("INSERT INTO analytics.fact_order VALUES (TIMESTAMP '2018-10-17 17:30:18')")
        db.close()
        cls.server = create_server(cls.database, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temporary.cleanup()

    def request_json(self, path: str, method: str = "GET") -> tuple[int, dict]:
        request = Request(self.base_url + path, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_explicit_month_reads_curated_value(self) -> None:
        status, body = self.request_json("/metrics/revenue?month=2017-11")
        self.assertEqual(status, 200)
        self.assertEqual(body["value"], "987765.37")
        self.assertEqual(body["delivered_orders"], 7289)
        self.assertEqual(body["source_table"], "analytics.mart_monthly_metrics")
        self.assertEqual(body["latest_source_purchase_date"], "2018-10-17")

    def test_latest_is_explicitly_historical(self) -> None:
        status, body = self.request_json("/metrics/revenue/latest")
        self.assertEqual(status, 200)
        self.assertEqual(body["month"], "2017-11")
        self.assertEqual(body["selection"], "latest_month_with_delivered_orders")

    def test_missing_month_does_not_fall_back(self) -> None:
        status, body = self.request_json("/metrics/revenue?month=2026-09")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "month_not_in_dataset")

    def test_invalid_and_extra_parameters_are_rejected(self) -> None:
        self.assertEqual(self.request_json("/metrics/revenue?month=2017-13")[0], 400)
        self.assertEqual(self.request_json("/metrics/revenue?month=0000-01")[0], 400)
        self.assertEqual(self.request_json("/metrics/revenue?month=2017-11&sql=SELECT")[0], 400)

    def test_sparse_month_is_labeled(self) -> None:
        status, body = self.request_json("/metrics/revenue?month=2018-09")
        self.assertEqual(status, 200)
        self.assertEqual(body["value"], "0.00")
        self.assertFalse(body["in_trend_window"])
        self.assertIn("Sparse", body["coverage_note"])

    def test_writes_are_rejected_and_tool_schema_is_served(self) -> None:
        self.assertEqual(self.request_json("/metrics/revenue", method="POST")[0], 405)
        status, body = self.request_json("/openapi.json")
        self.assertEqual(status, 200)
        self.assertIn("/metrics/revenue", body["paths"])


if __name__ == "__main__":
    unittest.main()

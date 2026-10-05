"""The GPT router may select only preapproved, source-backed metrics."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import duckdb

from assistant import answer_question, query_metric, route_question


class FakeClient:
    def __init__(self, metric: str, month: str | None):
        self.arguments = {"metric": metric, "month": month}
        self.responses = self
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(output=[SimpleNamespace(
            type="function_call", name="select_requested_metric",
            arguments=json.dumps(self.arguments),
        )])


class AssistantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.database = Path(cls.temporary.name) / "fixture.duckdb"
        db = duckdb.connect(str(cls.database))
        db.execute("CREATE SCHEMA analytics")
        db.execute("""CREATE TABLE analytics.mart_monthly_metrics (
            purchase_month DATE, merchandise_value DECIMAL(18,2),
            delivered_orders BIGINT, in_trend_window BOOLEAN,
            average_order_value DECIMAL(18,2))""")
        db.execute("""INSERT INTO analytics.mart_monthly_metrics VALUES
            (DATE '2017-11-01', 100.00, 2, true, 50.00)""")
        db.execute("CREATE TABLE analytics.fact_order (purchased_at TIMESTAMP)")
        db.execute("INSERT INTO analytics.fact_order VALUES (TIMESTAMP '2018-10-17 17:30:18')")
        db.execute("CREATE TABLE analytics.mart_customer_repeat (is_repeat_customer BOOLEAN)")
        db.execute("INSERT INTO analytics.mart_customer_repeat VALUES (true), (false)")
        db.execute("""CREATE TABLE analytics.mart_category_metrics (
            category_name VARCHAR, merchandise_value DECIMAL(18,2))""")
        db.execute("INSERT INTO analytics.mart_category_metrics VALUES ('books', 80), ('toys', 20)")
        db.execute("CREATE TABLE analytics.mart_delivery (is_late BOOLEAN)")
        db.execute("INSERT INTO analytics.mart_delivery VALUES (true), (false)")
        db.close()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_revenue_is_from_curated_mart(self):
        client = FakeClient("monthly_revenue", "2017-11")
        answer, result = answer_question("Ingresos en noviembre de 2017", self.database, client)
        self.assertIn("R$ 100.00", answer)
        self.assertEqual(result["source_table"], "analytics.mart_monthly_metrics")
        self.assertEqual(client.request["tools"][0]["parameters"]["additionalProperties"], False)
        self.assertFalse(client.request["store"])

    def test_all_other_requested_metrics(self):
        cases = [
            ("monthly_aov", "2017-11", "R$ 50.00"),
            ("repeat_purchase_rate", None, "50.00%"),
            ("top_categories", None, "books (R$ 80.00)"),
            ("late_delivery_rate", None, "50.00%"),
        ]
        for metric, month, expected in cases:
            with self.subTest(metric=metric):
                answer, _ = answer_question("test", self.database, FakeClient(metric, month))
                self.assertIn(expected, answer)

    def test_missing_month_never_substitutes_latest(self):
        answer, result = answer_question("Ingresos", self.database,
                                         FakeClient("monthly_revenue", None))
        self.assertEqual(result["status"], "month_required")
        self.assertIn("Specify a month", answer)
        answer, result = answer_question("Ingresos en 2026-09", self.database,
                                         FakeClient("monthly_revenue", "2026-09"))
        self.assertEqual(result["status"], "month_unavailable")

    def test_unsupported_and_invalid_model_arguments(self):
        self.assertEqual(query_metric(self.database, "unsupported", None)["status"], "unsupported")
        with self.assertRaises(ValueError):
            route_question("consulta", FakeClient("raw_sql", None))
        with self.assertRaises(ValueError):
            route_question("consulta", FakeClient("monthly_revenue", "2017-13"))
        with self.assertRaises(ValueError):
            query_metric(self.database, "monthly_revenue", "2017-11' OR TRUE --")
        self.assertEqual(query_metric(self.database, "late_delivery_rate", "2017-11")["status"],
                         "unsupported")


if __name__ == "__main__":
    unittest.main()

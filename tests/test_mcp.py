"""Exercise real MCP discovery/stdio calls, output validation and app integration."""
import asyncio
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from mcp import Client
from mcp.client.stdio import get_default_environment
from metric_contract import RevenueResult
from metrics import query_metric
from metrics_client import get_monthly_revenue, server_parameters
from openai_policy import reserve_request
from showcase_server import create_server
import test_assistant as fixtures


class MCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.AssistantTests.setUpClass()
        cls.database = fixtures.AssistantTests.database

    @classmethod
    def tearDownClass(cls):
        fixtures.AssistantTests.tearDownClass()

    def test_real_protocol_discovery_and_guardrails(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()

        async def exercise():
            async with Client(server_parameters(self.database), read_timeout_seconds=10) as client:
                tools = (await client.list_tools()).tools
                self.assertEqual([tool.name for tool in tools], ["get_monthly_revenue"])
                self.assertIsNotNone(tools[0].output_schema)
                self.assertFalse(tools[0].input_schema["additionalProperties"])
                self.assertTrue(tools[0].annotations.read_only_hint)
                success = await client.call_tool("get_monthly_revenue", {"month": "2017-11"})
                self.assertFalse(success.is_error)
                self.assertEqual(success.structured_content["value"], "100.00")
                for arguments in ({"month": "0000-01"}, {"month": "2017-11' OR TRUE --"}, {}, {"month": 201711},
                                  {"month": "2017-11", "sql": "SELECT *"}):
                    result = await client.call_tool("get_monthly_revenue", arguments)
                    self.assertTrue(result.is_error, arguments)
                unknown = await client.call_tool("execute_sql", {"sql": "DELETE FROM analytics.fact_order"})
                self.assertTrue(unknown.is_error)

        asyncio.run(exercise())
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before)

    def test_same_service_values_and_explicit_coverage(self):
        for month in ("2017-11", "latest", "2026-09"):
            self.assertEqual(get_monthly_revenue(self.database, month),
                             query_metric(self.database, "monthly_revenue", month))

    def test_secret_is_not_forwarded(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-sentinel", "OTHER_SECRET": "test-other"}):
            params = server_parameters(self.database)
            self.assertEqual(params.env["OPENAI_API_KEY"], "")
            self.assertNotIn("OTHER_SECRET", params.env)
            self.assertNotIn("OPENAI_API_KEY", get_default_environment())

    def test_output_requires_complete_and_exact_monetary_result(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            RevenueResult.model_validate({"status": "ok", "month": "2017-11"})
        result = query_metric(self.database, "monthly_revenue", "2017-11")
        result["value"] = 100.0
        with self.assertRaises(ValidationError):
            RevenueResult.model_validate(result)

    def test_dashboard_direct_and_gpt_queries_reach_mcp(self):
        server = create_server(self.database, port=0,
                               client_factory=lambda: fixtures.FakeClient("monthly_revenue", "2017-11"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-sentinel"}):
                for path, body in (("/api/revenue", {"month": "2017-11"}),
                                   ("/api/ask", {"question": "Ingresos noviembre 2017"})):
                    request = Request(url+path, data=json.dumps(body).encode(),
                                      headers={"Content-Type": "application/json", "Origin": url})
                    with urlopen(request, timeout=20) as response:
                        payload = json.load(response)
                    self.assertEqual(payload["transport"], "mcp_stdio")
                    self.assertIn("R$ 100.00", payload["answer"])
            # Direct MCP requests remain available with no OpenAI credential.
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
                request = Request(url+"/api/revenue", data=b'{"month":"latest"}',
                                  headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=20) as response:
                    self.assertEqual(json.load(response)["status"], "ok")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_persistent_openai_attempt_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.sqlite3"
            for _ in range(20):
                reserve_request(path)
            with self.assertRaisesRegex(RuntimeError, "20 GPT requests"):
                reserve_request(path)


if __name__ == "__main__":
    unittest.main()

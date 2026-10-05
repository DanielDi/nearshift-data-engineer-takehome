"""Hosted access, origin enforcement, packaging equivalence and fail-closed AI."""
import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from deploy.render_build import compact_database
from hosting_policy import HostingPolicy
from metrics import query_metric
from openai_policy import reserve_request
from showcase_server import create_server
import test_assistant as fixtures


class HostingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.AssistantTests.setUpClass()
        cls.database = fixtures.AssistantTests.database

    @classmethod
    def tearDownClass(cls):
        fixtures.AssistantTests.tearDownClass()

    def test_public_configuration_requires_https_and_access_secret(self):
        for origin, password in (("http://demo.onrender.com", "long-test-password"),
                                 ("https://demo.onrender.com/path", "long-test-password"),
                                 ("https://demo.onrender.com", "short")):
            with self.assertRaises(ValueError):
                HostingPolicy(origin, password=password)

    def test_hosted_requests_authenticate_and_validate_origin(self):
        policy = HostingPolicy("https://demo.onrender.com", password="fixture-review-password")
        server = create_server(self.database, port=0, policy=policy,
                               client_factory=lambda: fixtures.FakeClient("monthly_aov", "2017-11"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        authorization = 'Basic ' + base64.b64encode(b'reviewer:fixture-review-password').decode()

        def request(path, *, body=None, headers=None):
            req = Request(url + path, data=json.dumps(body).encode() if body else None,
                          headers=headers or {})
            try:
                with urlopen(req, timeout=20) as response:
                    return response.status, response.headers, json.load(response) if path != '/' else response.read()
            except HTTPError as error:
                return error.code, error.headers, json.load(error)
        try:
            self.assertEqual(request('/health')[2], {"status": "ok"})
            headers = {"Host": "demo.onrender.com", "X-Forwarded-Proto": "https"}
            status, response_headers, _ = request('/', headers=headers)
            self.assertEqual(status, 401)
            self.assertIn('Basic', response_headers['WWW-Authenticate'])
            headers['Authorization'] = authorization
            self.assertEqual(request('/', headers=headers)[0], 200)
            headers.update({"Content-Type": "application/json", "Origin": policy.origin})
            # No cloud counter -> no paid model request, even if a key exists.
            with patch.dict('os.environ', {"OPENAI_API_KEY": "fixture-key", "OPENAI_USAGE_DATABASE_URL": ""}):
                self.assertEqual(request('/api/ask', body={"question": "AOV 2017-11"}, headers=headers)[0], 503)
            # The approved MCP route remains usable without the AI counter/key.
            status, _, payload = request('/api/revenue', body={"month": "2017-11"}, headers=headers)
            self.assertEqual(status, 200)
            self.assertEqual(payload['result']['value'], '100.00')
            for key, value in (("Origin", "https://attacker.example"), ("Host", "attacker.example"),
                               ("X-Forwarded-Proto", "http"), ("Authorization", "Basic invalid")):
                changed = {**headers, key: value}
                expected = 401 if key == 'Authorization' else 403
                self.assertEqual(request('/api/revenue', body={"month": "2017-11"}, headers=changed)[0], expected)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_hosted_budget_does_not_fall_back_to_ephemeral_sqlite(self):
        with patch.dict('os.environ', {"RENDER": "true", "OPENAI_USAGE_DATABASE_URL": ""}):
            with self.assertRaisesRegex(RuntimeError, 'persistent usage counter'):
                reserve_request()
        with patch.dict('os.environ', {"OPENAI_USAGE_DATABASE_URL": "postgresql://localhost:1/unavailable"}):
            with self.assertRaisesRegex(RuntimeError, 'no OpenAI request was sent'):
                reserve_request()

    def test_serving_snapshot_preserves_all_metric_values(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'serving.duckdb'
            compact_database(self.database, output)
            for metric, month in (("monthly_revenue", "latest"), ("monthly_aov", "2017-11"),
                                  ("repeat_purchase_rate", None), ("top_categories", None),
                                  ("late_delivery_rate", None)):
                self.assertEqual(query_metric(self.database, metric, month), query_metric(output, metric, month))
            import duckdb
            with duckdb.connect(str(output), read_only=True) as db:
                columns = {row[0] for row in db.execute('SELECT column_name FROM information_schema.columns').fetchall()}
                self.assertNotIn('customer_id', columns)
                self.assertNotIn('customer_unique_id', columns)
                self.assertNotIn('order_id', columns)


if __name__ == '__main__':
    unittest.main()

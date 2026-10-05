"""The showcase stays usable without an OpenAI balance or database download."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from showcase_server import create_server


class ShowcaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.database = Path(cls.temporary.name) / "placeholder.duckdb"
        cls.database.touch()
        cls.server = create_server(cls.database, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temporary.cleanup()

    def request(self, path, method="GET", body=None, content_type="application/json"):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.url + path, method=method, data=data,
                          headers={"Content-Type": content_type})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_page_and_report_are_available(self):
        status, html = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"dashboard-data", html)
        self.assertIn(b"13221498.11", html)
        self.assertIn("La solución, de extremo a extremo".encode("utf-8"), html)
        self.assertIn(b'aria-labelledby="architecture-title"', html)
        self.assertEqual(self.request("/reports/monthly_metrics.csv")[0], 200)
        self.assertEqual(self.request("/sql/model.sql")[0], 200)
        self.assertEqual(self.request("/../../data/nearshift.duckdb")[0], 404)

    def test_free_text_has_clear_no_key_state(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            status, body = self.request("/api/ask", method="POST", body={"question": "AOV 2017-11"})
        self.assertEqual(status, 503)
        self.assertIn("OPENAI_API_KEY", body.decode("utf-8"))

    def test_request_shape_is_bounded(self):
        self.assertEqual(self.request("/api/ask", method="POST", body={"sql": "select *"})[0], 400)
        self.assertEqual(self.request("/api/ask", method="POST", body={"question": "x" * 1001})[0], 400)
        self.assertEqual(self.request("/api/ask", method="PUT")[0], 405)


if __name__ == "__main__":
    unittest.main()

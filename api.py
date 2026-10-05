"""Read-only local HTTP API for the curated Olist revenue proxy."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import duckdb


from metrics import DEFAULT_DB, ROOT, MONTH_PATTERN, query_month

OPENAPI_PATH = ROOT / "api" / "openapi.json"


def create_server(database_path: Path, port: int = 8000) -> ThreadingHTTPServer:
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError(
            f"Database not found: {database_path}. Run `python run.py` first."
        )
    # Fail during startup when a supplied file lacks the modeled tables.
    db = duckdb.connect(str(database_path), read_only=True)
    try:
        db.execute("SELECT purchase_month FROM analytics.mart_monthly_metrics LIMIT 0")
        db.execute("SELECT purchased_at FROM analytics.fact_order LIMIT 0")
    finally:
        db.close()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if len(self.path) > 1024:
                self.respond(414, {"error": "request_uri_too_long"})
                return
            parsed = urlsplit(self.path)
            if parsed.path == "/openapi.json" and not parsed.query:
                self.respond(200, json.loads(OPENAPI_PATH.read_text(encoding="utf-8")))
                return
            if parsed.path == "/health" and not parsed.query:
                self.respond(200, {"status": "ok", "database": "modeled_data_ready"})
                return
            if parsed.path == "/metrics/revenue/latest" and not parsed.query:
                try:
                    result = query_month(database_path, None)
                except duckdb.Error:
                    self.respond(503, {"error": "modeled_data_unavailable"})
                    return
                if result is None:
                    self.respond(404, {"error": "no_delivered_month_available"})
                else:
                    result["selection"] = "latest_month_with_delivered_orders"
                    self.respond(200, result)
                return
            if parsed.path == "/metrics/revenue":
                params = parse_qs(parsed.query, keep_blank_values=True)
                if set(params) != {"month"} or len(params["month"]) != 1:
                    self.respond(400, {"error": "month_parameter_required"})
                    return
                month_text = params["month"][0]
                if not MONTH_PATTERN.fullmatch(month_text):
                    self.respond(400, {"error": "invalid_month", "expected": "YYYY-MM"})
                    return
                try:
                    month = date.fromisoformat(month_text + "-01")
                except ValueError:
                    self.respond(400, {"error": "invalid_month", "expected": "YYYY-MM"})
                    return
                try:
                    result = query_month(database_path, month)
                except duckdb.Error:
                    self.respond(503, {"error": "modeled_data_unavailable"})
                    return
                if result is None:
                    self.respond(404, {"error": "month_not_in_dataset", "month": month_text})
                else:
                    result["selection"] = "explicit_month"
                    self.respond(200, result)
                return
            self.respond(404, {"error": "not_found"})

        def do_POST(self) -> None:
            self.respond(405, {"error": "read_only_api"})

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        server = create_server(args.db, args.port)
    except (FileNotFoundError, duckdb.Error) as error:
        parser.exit(1, f"API startup failed: {error}\n")
    print(f"Read-only Olist API: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

"""Serve the standalone showcase and its optional GPT question endpoint locally."""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI, RateLimitError

from assistant import answer_question, create_openai_client, format_answer
from metrics_client import get_monthly_revenue
from build_showcase import ROOT, build_showcase
from hosting_policy import HostingPolicy


ALLOWED_FILES = {
    "/": ROOT / "showcase" / "index.html",
    "/index.html": ROOT / "showcase" / "index.html",
    "/README.md": ROOT / "README.md",
    "/reports/INSIGHTS.md": ROOT / "reports" / "INSIGHTS.md",
    "/reports/VALIDATION.md": ROOT / "reports" / "VALIDATION.md",
    "/reports/monthly_metrics.csv": ROOT / "reports" / "monthly_metrics.csv",
    "/reports/category_metrics.csv": ROOT / "reports" / "category_metrics.csv",
    "/sql/model.sql": ROOT / "sql" / "model.sql",
}
CONTENT_TYPES = {".html": "text/html", ".md": "text/markdown", ".csv": "text/csv", ".sql": "text/plain"}


def create_server(database_path: Path, port: int = 8001,
                  client_factory=create_openai_client, *,
                  policy: HostingPolicy | None = None) -> ThreadingHTTPServer:
    policy = policy or HostingPolicy()
    query_slot = threading.BoundedSemaphore(1)
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError("No database found. Run python run.py first.")
    if not (ROOT / "showcase" / "index.html").is_file():
        raise FileNotFoundError("No showcase found. Run python build_showcase.py first.")

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def require_access(self, *, write=False) -> bool:
            if not policy.request_allowed(self.headers, self.server.server_address[1], write=write):
                self.send_json(403, {"message": "Use the application's configured address and origin."})
                return False
            if not policy.authenticated(self.headers.get("Authorization")):
                self.send_json(401, {"message": "Reviewer sign-in is required."},
                               authenticate=True)
                return False
            return True

        def send_body(self, status: int, body: bytes, content_type: str, *, authenticate=False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'")
            if policy.origin:
                self.send_header("Strict-Transport-Security", "max-age=86400")
            if authenticate:
                self.send_header("WWW-Authenticate", 'Basic realm="NearShift review", charset="UTF-8"')
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, payload: dict, *, authenticate=False) -> None:
            self.send_body(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           "application/json", authenticate=authenticate)

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.query:
                self.send_json(400, {"message": "Query parameters are not accepted on this route."})
                return
            if parsed.path == "/health":
                # Readiness is public; credential/budget details stay behind sign-in.
                self.send_json(200, {"status": "ok"})
                return
            if not self.require_access():
                return
            if parsed.path == "/api/status":
                budget_ready = not policy.origin or bool(os.environ.get("OPENAI_USAGE_DATABASE_URL"))
                self.send_json(200, {"status": "ok", "gpt_configured": bool(os.environ.get("OPENAI_API_KEY")) and budget_ready})
                return
            path = ALLOWED_FILES.get(parsed.path)
            if path is None or not path.is_file():
                self.send_json(404, {"message": "Route not found."})
                return
            self.send_body(200, path.read_bytes(), CONTENT_TYPES[path.suffix])

        def do_POST(self) -> None:
            if not self.require_access(write=True):
                return
            if not query_slot.acquire(blocking=False):
                self.send_json(429, {"message": "Another query is running. Please try again shortly."})
                return
            try:
                self.query_POST()
            finally:
                query_slot.release()

        def query_POST(self) -> None:
            if self.path not in {"/api/ask", "/api/revenue"}:
                self.send_json(404, {"message": "Route not found."})
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json(415, {"message": "JSON is required."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= 4096:
                self.send_json(413, {"message": "The request is too large."})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_json(400, {"message": "Invalid JSON."})
                return
            if self.path == "/api/revenue":
                if not isinstance(body, dict) or set(body) != {"month"} or not isinstance(body["month"], str):
                    self.send_json(400, {"message": "A month in YYYY-MM format or latest is required."})
                    return
                try:
                    result = get_monthly_revenue(database_path, body["month"])
                except ValueError:
                    self.send_json(400, {"message": "Invalid month: use YYYY-MM or latest."})
                    return
                except RuntimeError:
                    self.send_json(503, {"message": "Unable to query MCP. Check the curated database."})
                    return
                self.send_json(200, {"answer": format_answer("monthly_revenue", result),
                                     "status": result["status"], "transport": "mcp_stdio", "result": result})
                return
            if not isinstance(body, dict) or set(body) != {"question"} or not isinstance(body["question"], str):
                self.send_json(400, {"message": "A text question is required."})
                return
            question = body["question"].strip()
            if not 0 < len(question) <= 1000:
                self.send_json(400, {"message": "The question must contain between 1 and 1000 characters."})
                return
            if not os.environ.get("OPENAI_API_KEY"):
                self.send_json(503, {"message": "GPT requires OPENAI_API_KEY and available API credits. Offline examples remain available."})
                return
            if policy.origin and not os.environ.get("OPENAI_USAGE_DATABASE_URL"):
                self.send_json(503, {"message": "AI queries need a persistent usage counter. Revenue lookup and offline examples remain available."})
                return
            try:
                answer, result = answer_question(question, database_path, client_factory())
            except RateLimitError as error:
                details = str(error.body) if error.body else ""
                message = ("The account has no API credits. Check OpenAI billing."
                           if "insufficient_quota" in details or "credit_balance_exhausted" in details
                           else "Temporary API limit; try again later.")
                self.send_json(503, {"message": message})
                return
            except AuthenticationError:
                self.send_json(503, {"message": "The API key was not accepted."})
                return
            except APIConnectionError:
                self.send_json(503, {"message": "Unable to connect to the OpenAI API."})
                return
            except (APIError, duckdb.Error, ValueError):
                self.send_json(503, {"message": "Unable to complete the request."})
                return
            except RuntimeError as error:
                self.send_json(503, {"message": str(error)})
                return
            self.send_json(200, {"answer": answer, "status": result["status"],
                                 "transport": "mcp_stdio" if result.get("metric") == "delivered_merchandise_value" else "curated_service"})

        def do_PUT(self) -> None:
            self.send_json(405, {"message": "Read-only server."})

        do_PATCH = do_PUT
        do_DELETE = do_PUT

    return ThreadingHTTPServer(("0.0.0.0" if policy.origin else "127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "nearshift.duckdb")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8001")))
    parser.add_argument("--skip-build", action="store_true", help="Serve the previously built standalone page")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        policy = HostingPolicy.from_environment()
        if not args.skip_build:
            build_showcase(args.db, ROOT / "reports")
        if policy.origin and os.environ.get("OPENAI_USAGE_DATABASE_URL"):
            from openai_policy import initialize_hosted_budget
            initialize_hosted_budget()
        server = create_server(args.db, args.port, policy=policy)
    except (OSError, duckdb.Error, ValueError, RuntimeError) as error:
        parser.exit(1, f"Showcase startup failed: {error}\n")
    print(f"NearShift showcase: {policy.origin or f'http://127.0.0.1:{args.port}'} /", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

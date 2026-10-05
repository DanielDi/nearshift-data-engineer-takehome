"""Serve the standalone showcase and its optional GPT question endpoint locally."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI, RateLimitError

from assistant import answer_question
from build_showcase import ROOT, build_showcase


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
                  client_factory=OpenAI) -> ThreadingHTTPServer:
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError("No database found. Run python run.py first.")
    if not (ROOT / "showcase" / "index.html").is_file():
        raise FileNotFoundError("No showcase found. Run python build_showcase.py first.")

    class Handler(BaseHTTPRequestHandler):
        def send_body(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, payload: dict) -> None:
            self.send_body(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           "application/json")

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.query:
                self.send_json(400, {"message": "No se aceptan parámetros en esta ruta."})
                return
            if parsed.path == "/health":
                self.send_json(200, {"status": "ok", "gpt_configured": bool(os.environ.get("OPENAI_API_KEY"))})
                return
            path = ALLOWED_FILES.get(parsed.path)
            if path is None or not path.is_file():
                self.send_json(404, {"message": "Ruta no encontrada."})
                return
            self.send_body(200, path.read_bytes(), CONTENT_TYPES[path.suffix])

        def do_POST(self) -> None:
            if self.path != "/api/ask":
                self.send_json(404, {"message": "Ruta no encontrada."})
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json(415, {"message": "Se requiere JSON."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= 4096:
                self.send_json(413, {"message": "La solicitud es demasiado grande."})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_json(400, {"message": "JSON inválido."})
                return
            if not isinstance(body, dict) or set(body) != {"question"} or not isinstance(body["question"], str):
                self.send_json(400, {"message": "Se requiere una pregunta de texto."})
                return
            question = body["question"].strip()
            if not 0 < len(question) <= 1000:
                self.send_json(400, {"message": "La pregunta debe tener entre 1 y 1000 caracteres."})
                return
            if not os.environ.get("OPENAI_API_KEY"):
                self.send_json(503, {"message": "GPT requiere OPENAI_API_KEY y créditos API. Las consultas guiadas siguen disponibles."})
                return
            try:
                answer, result = answer_question(question, database_path, client_factory())
            except RateLimitError as error:
                details = str(error.body) if error.body else ""
                message = ("La cuenta no tiene créditos API. Revisa la facturación de OpenAI."
                           if "insufficient_quota" in details or "credit_balance_exhausted" in details
                           else "Límite temporal de la API; intenta más tarde.")
                self.send_json(503, {"message": message})
                return
            except AuthenticationError:
                self.send_json(503, {"message": "La clave API no fue aceptada."})
                return
            except APIConnectionError:
                self.send_json(503, {"message": "No se pudo conectar con la API de OpenAI."})
                return
            except (APIError, duckdb.Error, ValueError):
                self.send_json(503, {"message": "No se pudo completar la consulta."})
                return
            self.send_json(200, {"answer": answer, "status": result["status"]})

        def do_PUT(self) -> None:
            self.send_json(405, {"message": "Servidor de solo lectura."})

        do_PATCH = do_PUT
        do_DELETE = do_PUT

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "nearshift.duckdb")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        build_showcase(args.db, ROOT / "reports")
        server = create_server(args.db, args.port)
    except (OSError, duckdb.Error, ValueError) as error:
        parser.exit(1, f"Showcase startup failed: {error}\n")
    print(f"NearShift showcase: http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

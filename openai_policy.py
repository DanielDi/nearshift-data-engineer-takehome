"""Local demo policy: at most 20 OpenAI attempts per Bogota calendar day.

Reservations persist across restarts and CLI/dashboard processes. Failed API
attempts count too. This is a request cap, not an OpenAI billing spend limit.
"""
import sqlite3
import os
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo
from metrics import ROOT

DAILY_REQUEST_LIMIT = 20
COUNTER_SCHEMA = """CREATE TABLE IF NOT EXISTS daily_attempts (
    day DATE PRIMARY KEY,
    attempts INTEGER NOT NULL CHECK (attempts BETWEEN 1 AND 20))"""


def initialize_hosted_budget() -> None:
    """Create only the usage-counter table; never expose connection details."""
    import psycopg
    try:
        with psycopg.connect(os.environ["OPENAI_USAGE_DATABASE_URL"], connect_timeout=5, sslmode="require") as db:
            db.execute(COUNTER_SCHEMA)
    except Exception:
        raise RuntimeError("The persistent API usage counter is unavailable.") from None


def reserve_hosted_request(day: str) -> None:
    import psycopg
    try:
        with psycopg.connect(os.environ["OPENAI_USAGE_DATABASE_URL"], connect_timeout=5, sslmode="require") as db:
            # Single atomic statement serializes concurrent reservations across restarts.
            row = db.execute("""INSERT INTO daily_attempts (day, attempts) VALUES (%s, 1)
                ON CONFLICT (day) DO UPDATE SET attempts = daily_attempts.attempts + 1
                WHERE daily_attempts.attempts < %s RETURNING attempts""",
                (day, DAILY_REQUEST_LIMIT)).fetchone()
            db.execute("DELETE FROM daily_attempts WHERE day < %s::date - 7", (day,))
    except Exception:
        raise RuntimeError("The persistent API usage counter is unavailable; no OpenAI request was sent.") from None
    if row is None:
        raise RuntimeError("The limit of 20 GPT requests per day has been reached.")


def reserve_request(path=None) -> None:
    day = datetime.now(ZoneInfo("America/Bogota")).date().isoformat()
    if path is None and os.environ.get("OPENAI_USAGE_DATABASE_URL"):
        reserve_hosted_request(day)
        return
    if path is None and (os.environ.get("RENDER") == "true" or os.environ.get("APP_PUBLIC_URL")):
        raise RuntimeError("Hosted AI requires a persistent usage counter; no OpenAI request was sent.")
    path = path or ROOT / "data" / "openai_usage.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), timeout=5)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS daily_attempts (day TEXT PRIMARY KEY, attempts INTEGER NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT attempts FROM daily_attempts WHERE day = ?", (day,)).fetchone()
        if row and row[0] >= DAILY_REQUEST_LIMIT:
            raise RuntimeError("The local limit of 20 GPT requests per day has been reached.")
        db.execute("INSERT INTO daily_attempts VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET attempts=attempts+1", (day,))
        db.execute("DELETE FROM daily_attempts WHERE day < date(?, '-7 days')", (day,))

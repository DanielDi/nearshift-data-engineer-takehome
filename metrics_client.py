"""Bounded local MCP bridge used by the dashboard and GPT assistant."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from metric_contract import RevenueResult
from metrics import DEFAULT_DB, ROOT, MONTH_PATTERN


def server_parameters(database_path: Path) -> StdioServerParameters:
    # MCP SDK adds only its OS environment allowlist. Never pass os.environ wholesale.
    safe_names = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "HOME", "USERPROFILE"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in safe_names}
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["OPENAI_API_KEY"] = ""  # Explicit defense against future SDK inheritance changes.
    return StdioServerParameters(command=sys.executable,
                                 args=[str(ROOT / "metrics_mcp.py"), "--db", str(database_path.resolve())],
                                 cwd=str(ROOT), env=environment)


async def query_revenue(database_path: Path, month: str) -> dict:
    from datetime import date
    if not isinstance(month, str) or (month != "latest" and not MONTH_PATTERN.fullmatch(month)):
        raise ValueError("Invalid month: use YYYY-MM or latest.")
    if month != "latest":
        date.fromisoformat(month + "-01")
    try:
        async with asyncio.timeout(20):
            async with Client(server_parameters(database_path), read_timeout_seconds=15) as client:
                response = await client.call_tool("get_monthly_revenue", {"month": month})
                if response.is_error:
                    raise ValueError("MCP rejected the revenue request.")
                result = RevenueResult.model_validate(response.structured_content)
                if month != "latest" and result.month != month:
                    raise ValueError("MCP returned a different month than requested.")
                return result.model_dump(exclude_none=True)
    except ValueError:
        raise
    except Exception:
        # Protocol/process errors must not disclose environment or arbitrary server text.
        raise RuntimeError("Unable to connect to MCP or validate its result.") from None


def get_monthly_revenue(database_path: Path, month: str) -> dict:
    return asyncio.run(query_revenue(database_path, month))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("month", help="YYYY-MM or latest")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    try:
        print(json.dumps(get_monthly_revenue(args.db, args.month), ensure_ascii=False))
    except (ValueError, RuntimeError):
        parser.exit(1, "Unable to query MCP. Check the month and curated database.\n")


if __name__ == "__main__":
    main()

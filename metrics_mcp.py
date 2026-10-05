"""One local read-only MCP tool. No OpenAI dependency or credential is needed."""
from __future__ import annotations
import argparse
import json
import logging
import time
from pathlib import Path
from uuid import uuid4

import duckdb
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from metric_contract import RevenueResult
from metrics import DEFAULT_DB, query_metric

LOGGER = logging.getLogger("nearshift.metrics")


class StrictMetricsServer(MCPServer):
    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.input_schema["additionalProperties"] = False
            tool.input_schema["properties"]["month"].update(
                {"maxLength": 7, "pattern": r"^(latest|[0-9]{4}-(0[1-9]|1[0-2]))$"})
        return tools

    async def call_tool(self, name, arguments, *args, **kwargs):
        # Validate before SDK coercion/drop of unknown function arguments.
        if name != "get_monthly_revenue":
            raise ToolError("Unknown tool")
        if not isinstance(arguments, dict) or set(arguments) != {"month"} or not isinstance(arguments["month"], str):
            raise ToolError("Exactly one string argument 'month' is required")
        return await super().call_tool(name, arguments, *args, **kwargs)


def create_mcp(database_path: Path) -> MCPServer:
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError("Modeled database missing; run python run.py first.")
    server = StrictMetricsServer("nearshift-metrics", version="1.0.0", log_level="WARNING",
                       instructions="Historical Olist 2016–2018 aggregates only. Never label them current revenue.")

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                            idempotentHint=True, openWorldHint=False))
    def get_monthly_revenue(month: str) -> RevenueResult:
        """Delivered merchandise value in BRL. Require YYYY-MM or explicit 'latest'.

        Latest means the last source month with delivered orders, not last calendar
        month. Fixed SQL only; no customer records, refunds ledger or accounting revenue.
        """
        request_id, started, status = str(uuid4()), time.monotonic(), "error"
        audit_month = None
        try:
            # Validate before opening DuckDB and never log arbitrary supplied text.
            from datetime import date
            from metrics import MONTH_PATTERN
            if month != "latest":
                if not MONTH_PATTERN.fullmatch(month):
                    raise ToolError("Expected YYYY-MM or latest")
                try:
                    date.fromisoformat(month + "-01")
                except ValueError:
                    raise ToolError("Invalid calendar month") from None
            audit_month = month
            result = RevenueResult.model_validate(query_metric(database_path, "monthly_revenue", month))
            status = result.status
            return result
        except duckdb.Error:
            raise ToolError("Modeled data unavailable; rebuild the pipeline.") from None
        finally:
            LOGGER.warning(json.dumps({"request_id": request_id, "tool": "get_monthly_revenue",
                                       "month": audit_month, "status": status, "contract_version": "1.0.0",
                                       "duration_ms": round(1000 * (time.monotonic() - started))}))

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    logging.basicConfig(format="%(message)s")
    try:
        server = create_mcp(args.db)
    except (OSError, ValueError):
        parser.exit(1, "MCP startup failed: modeled database missing. Run python run.py first.\n")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

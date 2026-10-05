"""Versioned, strict MCP revenue input/output contracts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator


class RevenueResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["ok", "month_unavailable"]
    month: str
    metric: Literal["delivered_merchandise_value"] | None = None
    value: str | None = None
    currency: Literal["BRL"] | None = None
    delivered_orders: int | None = None
    definition: str | None = None
    source_table: Literal["analytics.mart_monthly_metrics"] | None = None
    in_trend_window: bool | None = None
    latest_source_purchase_date: str | None = None
    coverage_note: str | None = None

    @model_validator(mode="after")
    def complete_success(self):
        if self.status == "ok":
            if any(getattr(self, field) is None for field in type(self).model_fields):
                raise ValueError("Incomplete revenue result")
            from datetime import date
            from decimal import Decimal
            date.fromisoformat(self.month + "-01")
            date.fromisoformat(self.latest_source_purchase_date)
            amount = Decimal(self.value)
            if not amount.is_finite() or amount < 0 or self.delivered_orders < 0:
                raise ValueError("Invalid revenue value")
        return self

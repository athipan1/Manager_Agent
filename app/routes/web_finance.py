from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, field_validator

from ..database_client import DatabaseAgentClient
from ..dashboard_security import enforce_dashboard_rate_limit
from .web_control import (
    FinanceEntry,
    FinancialAdvisorRequest,
    StrictModel,
    build_financial_advice,
    require_operator_token,
)

router = APIRouter(prefix="/web-control", tags=["Web Personal Finance"])


class CreateFinanceEntryRequest(StrictModel):
    entry_id: str = Field(min_length=8, max_length=80)
    account_id: str | int
    entry_type: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Literal["THB"] = "THB"
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    occurred_at: str

    @field_validator("account_id", mode="before")
    @classmethod
    def normalize_account_id(cls, value: Any) -> str:
        return str(value)


class UpdateFinanceBudgetsRequest(StrictModel):
    personal_investment_budget_thb: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    trade_plan_limit_usd: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)


class PersistedFinancialAdvisorRequest(StrictModel):
    account_id: str | int
    message: str = Field(default="", max_length=2000)

    @field_validator("account_id", mode="before")
    @classmethod
    def normalize_account_id(cls, value: Any) -> str:
        return str(value)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


async def _finance_state(db_client: DatabaseAgentClient, account_id: str, correlation_id: str) -> dict[str, Any]:
    response_data = await db_client._get(
        f"/personal-finance/state?account_id={quote(str(account_id), safe='')}&limit=2000",
        correlation_id,
    )
    response = db_client.validate_standard_response(response_data)
    state = _jsonable(response.data)
    if not isinstance(state, dict):
        raise HTTPException(status_code=502, detail="Database Agent returned malformed personal finance state.")
    return state


@router.get("/finance-state")
async def get_finance_state(
    account_id: str = Query(..., min_length=1, max_length=80),
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    correlation_id = str(uuid.uuid4())
    async with DatabaseAgentClient() as db_client:
        state = await _finance_state(db_client, account_id, correlation_id)
    return {"status": "success", "data": state, "metadata": {"correlation_id": correlation_id}}


@router.post("/finance-entries")
async def create_finance_entry(
    request: CreateFinanceEntryRequest,
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    correlation_id = str(uuid.uuid4())
    async with DatabaseAgentClient() as db_client:
        response_data = await db_client._post(
            "/personal-finance/entries",
            correlation_id,
            json_data=request.model_dump(mode="json"),
        )
        response = db_client.validate_standard_response(response_data)
    return {"status": "success", "data": _jsonable(response.data), "metadata": {"correlation_id": correlation_id}}


@router.delete("/finance-entries/{entry_id}")
async def delete_finance_entry(
    entry_id: str,
    account_id: str = Query(..., min_length=1, max_length=80),
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    correlation_id = str(uuid.uuid4())
    async with DatabaseAgentClient() as db_client:
        response = await db_client._request(
            "DELETE",
            f"/personal-finance/entries/{quote(entry_id, safe='')}?account_id={quote(account_id, safe='')}",
            correlation_id,
        )
        standard_response = db_client.validate_standard_response(response.json())
    return {"status": "success", "data": _jsonable(standard_response.data), "metadata": {"correlation_id": correlation_id}}


@router.post("/finance-budgets/{account_id}")
async def update_finance_budgets(
    account_id: str,
    request: UpdateFinanceBudgetsRequest,
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    correlation_id = str(uuid.uuid4())
    async with DatabaseAgentClient() as db_client:
        response_data = await db_client._post(
            f"/personal-finance/budgets/{quote(account_id, safe='')}",
            correlation_id,
            json_data=request.model_dump(mode="json"),
        )
        response = db_client.validate_standard_response(response_data)
    return {"status": "success", "data": _jsonable(response.data), "metadata": {"correlation_id": correlation_id}}


@router.post("/financial-advisor-persisted")
async def financial_advisor_from_persisted_state(
    request: PersistedFinancialAdvisorRequest,
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    correlation_id = str(uuid.uuid4())
    async with DatabaseAgentClient() as db_client:
        state = await _finance_state(db_client, request.account_id, correlation_id)

    entries = [FinanceEntry.model_validate(entry) for entry in (state.get("entries") or [])]
    budgets = state.get("budgets") if isinstance(state.get("budgets"), dict) else {}
    advice_request = FinancialAdvisorRequest(
        account_id=request.account_id,
        entries=entries,
        available_investment_capital=budgets.get("personal_investment_budget_thb") or 0,
        message=request.message,
    )
    return {
        "status": "success",
        "data": build_financial_advice(advice_request),
        "metadata": {"correlation_id": correlation_id, "source": "database-agent"},
    }

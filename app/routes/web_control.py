from __future__ import annotations

import datetime as dt
import hmac
import os
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import config
from ..contracts import TradePlan
from ..database_client import DatabaseAgentClient
from ..dashboard_security import enforce_dashboard_rate_limit
from ..execution_client import ExecutionAgentClient
from ..models import AgentRequestBody
from ..workflows.single_analysis_workflow import run_single_analysis_flow

router = APIRouter(prefix="/web-control", tags=["Web Control Center"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FinanceEntry(StrictModel):
    entry_type: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    occurred_at: dt.datetime


class FinancialAdvisorRequest(StrictModel):
    account_id: str | int
    entries: list[FinanceEntry] = Field(default_factory=list, max_length=2000)
    available_investment_capital: Decimal = Field(default=Decimal("0"), ge=0)
    message: str = Field(default="", max_length=2000)

    @field_validator("account_id", mode="before")
    @classmethod
    def normalize_account_id(cls, value: Any) -> str:
        return str(value)


class InvestmentPlanRequest(StrictModel):
    account_id: str | int
    ticker: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-]+$")
    period: str = Field(default="1mo", max_length=16)
    user_goal: str = Field(default="", max_length=1000)
    max_investment_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)

    @field_validator("account_id", mode="before")
    @classmethod
    def normalize_account_id(cls, value: Any) -> str:
        return str(value)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.upper()


class ConfirmTradePlanRequest(StrictModel):
    account_id: str | int
    confirmation_text: str = Field(min_length=1, max_length=240)

    @field_validator("account_id", mode="before")
    @classmethod
    def normalize_account_id(cls, value: Any) -> str:
        return str(value)


def _operator_token() -> str:
    token = os.getenv("WEB_CONTROL_OPERATOR_TOKEN", "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WEB_CONTROL_OPERATOR_TOKEN is not configured.",
        )
    return token


async def require_operator_token(
    supplied: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
) -> None:
    expected = _operator_token()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token.")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_financial_advice(request: FinancialAdvisorRequest) -> dict[str, Any]:
    income = sum((entry.amount for entry in request.entries if entry.entry_type == "income"), Decimal("0"))
    expense = sum((entry.amount for entry in request.entries if entry.entry_type == "expense"), Decimal("0"))
    cash_flow = income - expense
    categories: dict[str, Decimal] = {}
    for entry in request.entries:
        if entry.entry_type == "expense":
            categories[entry.category] = categories.get(entry.category, Decimal("0")) + entry.amount

    largest_categories = sorted(categories.items(), key=lambda item: item[1], reverse=True)[:3]
    investable_from_cash_flow = max(Decimal("0"), cash_flow * Decimal("0.20"))
    suggested_investment = min(request.available_investment_capital, investable_from_cash_flow)
    reserve_target = max(Decimal("0"), expense * Decimal("3"))
    daily_budget = max(Decimal("0"), cash_flow / Decimal("30"))

    advice: list[str] = []
    if cash_flow < 0:
        advice.append("รายจ่ายสูงกว่ารายรับ ควรหยุดเพิ่มวงเงินลงทุนใหม่และลดหมวดรายจ่ายหลักก่อน")
    elif cash_flow == 0:
        advice.append("กระแสเงินสดยังไม่เหลือ ควรสร้างเงินสำรองก่อนเพิ่มความเสี่ยงในการลงทุน")
    else:
        advice.append("กระแสเงินสดเป็นบวก แบ่งเงินส่วนเกินระหว่างเงินสำรองและเงินลงทุนตามเพดานที่ตั้งไว้")
    if largest_categories:
        advice.append(f"หมวดรายจ่ายสูงสุดคือ {largest_categories[0][0]} ควรตรวจรายการย่อยในหมวดนี้ก่อน")
    if request.available_investment_capital > cash_flow and cash_flow > 0:
        advice.append("วงเงินลงทุนสูงกว่ากระแสเงินสดสุทธิ ควรหลีกเลี่ยงการใช้เงินฉุกเฉินหรือเงินที่มีภาระผูกพัน")
    advice.append("ทุกคำสั่งซื้อขายต้องผ่านแผน, Risk approval และการยืนยันจากผู้ใช้ ไม่ส่งคำสั่งจากบทสนทนาโดยอัตโนมัติ")

    return {
        "account_id": request.account_id,
        "currency": "THB",
        "summary": {
            "total_income": str(_money(income)),
            "total_expense": str(_money(expense)),
            "net_cash_flow": str(_money(cash_flow)),
            "available_investment_capital": str(_money(request.available_investment_capital)),
            "suggested_new_investment_cap": str(_money(suggested_investment)),
            "three_month_reserve_target": str(_money(reserve_target)),
            "indicative_daily_budget": str(_money(daily_budget)),
        },
        "largest_expense_categories": [
            {"category": category, "amount": str(_money(amount))}
            for category, amount in largest_categories
        ],
        "advice": advice,
        "answer": " ".join(advice),
        "user_message": request.message,
    }


def _find_trade_plan_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("trade_plan_id", "plan_id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for child in value.values():
            found = _find_trade_plan_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_trade_plan_id(child)
            if found:
                return found
    return None


def _plan_notional(plan: TradePlan) -> Decimal:
    reference_price = Decimal(str(plan.limit_price or plan.entry_price or 0))
    return reference_price * Decimal(plan.final_quantity or plan.quantity)


def confirmation_phrase(trade_plan_id: str) -> str:
    mode = str(config.TRADING_MODE or "paper").strip().upper()
    return f"CONFIRM {mode} {trade_plan_id}"


def _execution_enabled() -> bool:
    return os.getenv("WEB_CONTROL_ALLOW_EXECUTION", "false").strip().lower() in {"1", "true", "yes", "on"}


def _live_execution_enabled() -> bool:
    return os.getenv("WEB_CONTROL_ALLOW_LIVE_EXECUTION", "false").strip().lower() in {"1", "true", "yes", "on"}


def _plan_age_seconds(record: dict[str, Any]) -> float:
    raw = record.get("updated_at") or record.get("created_at")
    if not raw:
        return float("inf")
    timestamp = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.UTC)
    return max(0.0, (dt.datetime.now(dt.UTC) - timestamp).total_seconds())


async def _get_trade_plan(db_client: DatabaseAgentClient, trade_plan_id: str, correlation_id: str) -> dict[str, Any]:
    response_data = await db_client._get(f"/trade-plans/{quote(trade_plan_id, safe='')}", correlation_id)
    response = db_client.validate_standard_response(response_data)
    record = _jsonable(response.data)
    if not isinstance(record, dict):
        raise HTTPException(status_code=502, detail="Database Agent returned a malformed TradePlan.")
    return record


async def _update_trade_plan_status(
    db_client: DatabaseAgentClient,
    trade_plan_id: str,
    correlation_id: str,
    *,
    status_value: str,
    reason: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    response_data = await db_client._post(
        f"/trade-plans/{quote(trade_plan_id, safe='')}/status",
        correlation_id,
        json_data={"status": status_value, "reason": reason, "metadata": metadata},
    )
    response = db_client.validate_standard_response(response_data)
    return _jsonable(response.data)


@router.get("/capabilities")
async def capabilities(
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    return {
        "status": "success",
        "data": {
            "schema_version": "web-control.v1",
            "trading_mode": config.TRADING_MODE,
            "trading_enabled": config.TRADING_ENABLED,
            "manual_confirmation_required": True,
            "execution_enabled": _execution_enabled(),
            "live_execution_enabled": _live_execution_enabled(),
        },
    }


@router.post("/financial-advisor")
async def financial_advisor(
    request: FinancialAdvisorRequest,
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    return {"status": "success", "data": build_financial_advice(request)}


@router.post("/investment-plans")
async def create_investment_plan(
    request: InvestmentPlanRequest,
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    result = await run_single_analysis_flow(
        AgentRequestBody(ticker=request.ticker, period=request.period, account_id=request.account_id),
        dry_run=True,
    )
    payload = _jsonable(result)
    trade_plan_id = _find_trade_plan_id(payload)
    budget_metadata: dict[str, Any] = {
        "source": "web-control",
        "user_goal": request.user_goal,
        "web_control_max_investment_amount": str(_money(request.max_investment_amount)),
    }
    budget_blocked = False
    plan_notional: Decimal | None = None
    if trade_plan_id:
        correlation_id = str(uuid.uuid4())
        async with DatabaseAgentClient() as db_client:
            record = await _get_trade_plan(db_client, trade_plan_id, correlation_id)
            plan = TradePlan.model_validate(record.get("plan") or {})
            plan_notional = _plan_notional(plan)
            budget_metadata["web_control_plan_notional"] = str(_money(plan_notional))
            budget_blocked = plan_notional > request.max_investment_amount
            await _update_trade_plan_status(
                db_client,
                trade_plan_id,
                correlation_id,
                status_value="rejected" if budget_blocked else "queued",
                reason=(
                    "TradePlan exceeds the user-controlled investment allowance."
                    if budget_blocked
                    else "TradePlan reserved for explicit Web Control confirmation."
                ),
                metadata=budget_metadata,
            )

    return {
        "status": "success",
        "data": payload,
        "metadata": {
            "execution_attempted": False,
            "manual_confirmation_required": True,
            "trade_plan_id": trade_plan_id,
            "user_goal": request.user_goal,
            "max_investment_amount": str(_money(request.max_investment_amount)),
            "plan_notional": str(_money(plan_notional)) if plan_notional is not None else None,
            "budget_blocked": budget_blocked,
        },
    }


@router.get("/investment-plans/{trade_plan_id}")
async def get_investment_plan(
    trade_plan_id: str,
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    correlation_id = str(uuid.uuid4())
    async with DatabaseAgentClient() as db_client:
        record = await _get_trade_plan(db_client, trade_plan_id, correlation_id)
    return {
        "status": "success",
        "data": record,
        "metadata": {"confirmation_phrase": confirmation_phrase(trade_plan_id)},
    }


@router.post("/investment-plans/{trade_plan_id}/confirm")
async def confirm_investment_plan(
    trade_plan_id: str,
    request: ConfirmTradePlanRequest,
    _: None = Depends(require_operator_token),
    __: None = Depends(enforce_dashboard_rate_limit),
):
    if not _execution_enabled():
        raise HTTPException(status_code=409, detail="Web execution is disabled by WEB_CONTROL_ALLOW_EXECUTION.")
    if not config.TRADING_ENABLED:
        raise HTTPException(status_code=409, detail="Manager trading is disabled.")

    mode = str(config.TRADING_MODE or "paper").strip().lower()
    if mode == "live" and (not config.ALLOW_LIVE_TRADING or not _live_execution_enabled()):
        raise HTTPException(status_code=409, detail="Live web execution is disabled.")

    expected_confirmation = confirmation_phrase(trade_plan_id)
    if not hmac.compare_digest(request.confirmation_text.strip(), expected_confirmation):
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation text must exactly match: {expected_confirmation}",
        )

    correlation_id = str(uuid.uuid4())
    async with DatabaseAgentClient() as db_client:
        record = await _get_trade_plan(db_client, trade_plan_id, correlation_id)
        if str(record.get("account_id")) != request.account_id:
            raise HTTPException(status_code=403, detail="TradePlan does not belong to this account.")

        lifecycle_status = str(record.get("status") or "").lower()
        if lifecycle_status not in {"queued", "risk_approved"}:
            raise HTTPException(status_code=409, detail=f"TradePlan status {lifecycle_status!r} cannot be confirmed.")

        ttl_seconds = int(os.getenv("WEB_CONTROL_CONFIRMATION_TTL_SECONDS", "900"))
        if _plan_age_seconds(record) > ttl_seconds:
            raise HTTPException(status_code=409, detail="TradePlan confirmation window has expired. Create a fresh plan.")

        plan = TradePlan.model_validate(record.get("plan") or {})
        if plan.plan_id != trade_plan_id:
            raise HTTPException(status_code=409, detail="TradePlan identity mismatch.")
        if not plan.risk_approval_id:
            raise HTTPException(status_code=409, detail="TradePlan has no Risk approval.")

        approval = await db_client.get_risk_approval(plan.risk_approval_id, correlation_id)
        approval_status = str((approval or {}).get("status") or "").lower()
        approval_flag = bool((approval or {}).get("approved"))
        if not approval or (approval_status not in {"approved", "risk_approved", "active"} and not approval_flag):
            raise HTTPException(status_code=409, detail="Risk approval is missing or no longer approved.")

        order_notional = _plan_notional(plan)
        record_metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        user_limit_raw = str(record_metadata.get("web_control_max_investment_amount") or "").strip()
        if not user_limit_raw:
            raise HTTPException(status_code=409, detail="TradePlan has no persisted user investment allowance.")
        if order_notional > Decimal(user_limit_raw):
            raise HTTPException(status_code=409, detail="TradePlan exceeds the user-controlled investment allowance.")

        max_notional_raw = os.getenv("WEB_CONTROL_MAX_ORDER_NOTIONAL", "").strip()
        if max_notional_raw and order_notional > Decimal(max_notional_raw):
            raise HTTPException(status_code=409, detail="TradePlan exceeds WEB_CONTROL_MAX_ORDER_NOTIONAL.")

        execution_order = plan.to_execution_order()
        async with ExecutionAgentClient() as execution_client:
            execution = await execution_client.create_order(execution_order, correlation_id)

        execution_payload = _jsonable(execution)
        rejected = str(execution_payload.get("status") or "").lower() in {"failed", "rejected", "cancelled"}
        next_status = "rejected" if rejected else "execution_submitted"
        await _update_trade_plan_status(
            db_client,
            trade_plan_id,
            correlation_id,
            status_value=next_status,
            reason="User confirmed from Web Control Center.",
            metadata={
                "source": "web-control",
                "operator_confirmed": True,
                "trading_mode": mode,
                "execution": execution_payload,
            },
        )

    return {
        "status": "success" if not rejected else "failed",
        "data": execution_payload,
        "metadata": {
            "trade_plan_id": trade_plan_id,
            "correlation_id": correlation_id,
            "operator_confirmed": True,
        },
    }

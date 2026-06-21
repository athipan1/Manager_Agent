from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
import uuid
import datetime
from typing import List, Union, Dict, Any, Optional
from decimal import Decimal
import asyncio

from . import config
from .models import (
    AgentRequestBody, OrchestratorResponse, ReportDetail, ReportDetails,
    MultiAgentRequestBody, MultiOrchestratorResponse,
    AssetResult, ExecutionSummary, AnalysisResult, ExecutionResult,
    ScanAndAnalyzeRequest, DiscoverAnalyzeTradeRequest,
)
from .agent_client import call_agents
from .scanner_client import ScannerAgentClient
from .database_client import DatabaseAgentClient
from .execution_client import ExecutionAgentClient
from .contracts import CreateOrderRequest, StandardAgentResponse, ScannerResponseData, ScannerCandidate
from .resilient_client import AgentUnavailable
from .synthesis import get_weighted_verdict, get_reasons
from .logger import report_logger
from .risk_manager import assess_trade
from .portfolio_risk_manager import assess_portfolio_trades
from .config_manager import config_manager
from .learning_client import LearningAgentClient
from .context_numbers import active_value
from .risk_approval_contract import persist_risk_approval
from .stock_guard import StockGuardError, validate_stock_scope, validate_trade_action
from .stock_preflight import run_stock_live_preflight

app = FastAPI()


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _manager_metadata(*, risk_context_loaded: bool = False, learning_delta_applied: bool = False, learning_delta_pending: bool = False, learning_delta_skipped_reason: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    metadata = {
        "trading_mode": config.TRADING_MODE,
        "trading_enabled": config.TRADING_ENABLED,
        "allow_live_trading": config.ALLOW_LIVE_TRADING,
        "asset_class": config.ASSET_CLASS,
        "manual_approval_required": config.MANUAL_APPROVAL_REQUIRED,
        "risk_context_loaded": risk_context_loaded,
        "learning_delta_auto_apply_enabled": config.APPLY_LEARNING_DELTAS,
        "learning_delta_applied": learning_delta_applied,
        "learning_delta_pending": learning_delta_pending,
        "dry_run": dry_run,
    }
    if learning_delta_skipped_reason:
        metadata["learning_delta_skipped_reason"] = learning_delta_skipped_reason
    return metadata


def _apply_learning_deltas_if_allowed(learning_response: Any) -> Dict[str, Any]:
    if not learning_response or learning_response.learning_state == "warmup":
        return {"applied": False, "pending": False, "reason": "no_active_learning_delta"}
    deltas = learning_response.policy_deltas.model_dump(exclude_none=True)
    if not deltas:
        return {"applied": False, "pending": False, "reason": "empty_learning_delta"}
    if not config.APPLY_LEARNING_DELTAS:
        report_logger.warning("Learning policy deltas generated but not applied because APPLY_LEARNING_DELTAS=false.")
        return {"applied": False, "pending": True, "reason": "approval_required"}
    config_manager.apply_deltas(deltas)
    return {"applied": True, "pending": False, "reason": None}


def _response_to_dict(resp: Union[StandardAgentResponse, Dict[str, Any], Any]) -> Dict[str, Any]:
    if isinstance(resp, StandardAgentResponse):
        return resp.model_dump(mode="json")
    if isinstance(resp, dict):
        return resp
    if hasattr(resp, "model_dump"):
        return resp.model_dump(mode="json")
    return {}


def _normalize_score(value: Any) -> float:
    try:
        score = float(value or 0.0)
        score = score / 100.0 if score > 1.0 else score
        return max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        return 0.0


def _agent_data(resp: Union[StandardAgentResponse, Dict[str, Any], Any]) -> Dict[str, Any]:
    data = (_response_to_dict(resp).get("data") or {})
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return data if isinstance(data, dict) else {}


def _process_agent_response(resp: Union[StandardAgentResponse, Dict[str, Any]], agent_type: str) -> Optional[ReportDetail]:
    resp_dict = _response_to_dict(resp)
    if not resp_dict or resp_dict.get("status") != "success":
        return None
    data_obj = _agent_data(resp_dict)
    if not data_obj:
        return None
    action = str(data_obj.get("action") or "hold").lower()
    if action not in {"buy", "sell", "hold"}:
        action = "hold"
    score = _normalize_score(data_obj.get("confidence_score", 0.0))
    reason = data_obj.get("reason")
    tech_reason, fund_reason = get_reasons(action if agent_type == "technical" else "hold", action if agent_type == "fundamental" else "hold")
    return ReportDetail(action=action, score=score, reason=reason or (tech_reason if agent_type == "technical" else fund_reason))


def _as_decimal(value: Any) -> Decimal:
    try:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _position_exposure(position: Any) -> Decimal:
    if not position:
        return Decimal("0")
    qty = _as_decimal(getattr(position, "quantity", 0))
    price = _as_decimal(getattr(position, "current_market_price", None) or getattr(position, "average_cost", None))
    return abs(qty * price)


def _total_position_exposure(positions: List[Any]) -> Decimal:
    return sum((_position_exposure(position) for position in positions), Decimal("0"))


async def _fetch_context_value(db_client: DatabaseAgentClient, account_id: Union[int, str], correlation_id: str) -> Decimal:
    try:
        rows = await db_client.get_orders(account_id, correlation_id)
        return active_value(rows)
    except Exception as exc:
        if config.TRADING_MODE == "LIVE":
            raise AgentUnavailable(f"Required portfolio context unavailable: {exc}") from exc
        report_logger.warning(f"Portfolio context unavailable in PAPER mode; using zero value. correlation_id={correlation_id}: {exc}")
        return Decimal("0")


async def _fetch_session_risk_context(db_client: DatabaseAgentClient, account_id: Union[int, str], symbol: str, correlation_id: str) -> Dict[str, Any]:
    try:
        snapshot = await db_client.get_session_risk_snapshot(account_id, correlation_id, symbol=symbol)
        snapshot = _dict_or_empty(snapshot)
        snapshot.setdefault("emergency_halt", bool(getattr(config, "MANAGER_EMERGENCY_HALT", False)))
        if getattr(config, "MANAGER_EMERGENCY_HALT", False):
            snapshot["emergency_halt"] = True
        return snapshot
    except Exception as exc:
        if config.TRADING_MODE == "LIVE":
            raise AgentUnavailable(f"Required session risk context unavailable for {symbol}: {exc}") from exc
        report_logger.warning(f"Session risk context unavailable in PAPER mode for {symbol}; using safe zero context. correlation_id={correlation_id}: {exc}")
        return {
            "daily_realized_pnl": 0.0,
            "weekly_realized_pnl": 0.0,
            "consecutive_losses": 0,
            "trades_today": 0,
            "symbol_trades_today": 0,
            "minutes_since_last_loss": None,
            "minutes_since_last_symbol_trade": None,
            "emergency_halt": bool(getattr(config, "MANAGER_EMERGENCY_HALT", False)),
            "source": "manager_fallback",
        }


async def _fetch_session_risk_contexts(db_client: DatabaseAgentClient, account_id: Union[int, str], symbols: List[str], correlation_id: str) -> Dict[str, Any]:
    unique_symbols = [symbol for symbol in dict.fromkeys([str(s).upper() for s in symbols if s])]
    if not unique_symbols:
        return {}
    snapshots = await asyncio.gather(*[_fetch_session_risk_context(db_client, account_id, symbol, correlation_id) for symbol in unique_symbols])
    snapshots = [_dict_or_empty(snapshot) for snapshot in snapshots]
    first = snapshots[0] if snapshots else {}
    shared = {key: first.get(key) for key in ["daily_realized_pnl", "weekly_realized_pnl", "consecutive_losses", "trades_today", "minutes_since_last_loss", "emergency_halt"] if key in first}
    shared["symbol_contexts"] = {symbol: snapshot for symbol, snapshot in zip(unique_symbols, snapshots)}
    return shared


def _ensure_risk_approval_id(trade_decision: Optional[Dict[str, Any]], correlation_id: str) -> Optional[str]:
    if not trade_decision:
        return None
    risk_data = ((trade_decision.get("risk_agent_response") or {}).get("data") or {})
    approval_id = risk_data.get("risk_approval_id") or risk_data.get("approval_id") or trade_decision.get("risk_approval_id")
    if not approval_id:
        approval_id = f"risk-{correlation_id}-{trade_decision.get('symbol', 'unknown')}"
    trade_decision["risk_approval_id"] = str(approval_id)
    return str(approval_id)


def _dry_run_report(*, correlation_id: str, flow: str, symbol: Optional[str], analysis_result: Optional[Dict[str, Any]], trade_decision: Optional[Dict[str, Any]], execution_result: Optional[Dict[str, Any]], context_value: Decimal, dry_run: bool) -> Dict[str, Any]:
    return {"report_id": correlation_id, "flow": flow, "symbol": symbol, "dry_run": dry_run, "trading_mode": config.TRADING_MODE, "trading_enabled": config.TRADING_ENABLED, "risk_context": {"open_orders_exposure": _jsonable(context_value), "session": _jsonable((trade_decision or {}).get("session_risk_context")), "loaded": True}, "analysis": _jsonable(analysis_result), "trade_decision": _jsonable(trade_decision), "risk_approval_id": trade_decision.get("risk_approval_id") if trade_decision else None, "execution": _jsonable(execution_result), "generated_at": _now().isoformat()}


async def _audit_trade_decision(*, db_client: Optional[DatabaseAgentClient], account_id: Union[int, str], correlation_id: str, flow: str, symbol: str, analysis_result: Optional[Dict[str, Any]], trade_decision: Optional[Dict[str, Any]], execution_result: Optional[Dict[str, Any]], context_value: Decimal, dry_run: bool = False) -> Dict[str, Any]:
    audit = _dry_run_report(correlation_id=correlation_id, flow=flow, symbol=symbol, analysis_result=analysis_result, trade_decision=trade_decision, execution_result=execution_result, context_value=context_value, dry_run=dry_run)
    report_logger.info(f"trade_decision_audit={_jsonable(audit)}")
    if db_client is not None:
        try:
            await db_client.save_signal(account_id=account_id, symbol=symbol, correlation_id=correlation_id, final_verdict=(analysis_result or {}).get("final_verdict"), metadata={"audit": _jsonable(audit), "risk_approval_id": audit.get("risk_approval_id"), "dry_run": dry_run, "flow": flow})
        except Exception as exc:
            report_logger.warning(f"Failed to persist trade decision audit for {symbol}: {exc}, correlation_id={correlation_id}")
    return audit


async def _persist_signal(db_client: DatabaseAgentClient, account_id: Union[int, str], analysis_result: dict, correlation_id: str, extra_metadata: Optional[Dict[str, Any]] = None) -> None:
    try:
        details = analysis_result.get("details")
        tech_detail = details.technical if details else None
        fund_detail = details.fundamental if details else None
        await db_client.save_signal(account_id=account_id, symbol=analysis_result.get("ticker"), correlation_id=correlation_id, technical_score=tech_detail.score if tech_detail else None, fundamental_score=fund_detail.score if fund_detail else None, final_verdict=analysis_result.get("final_verdict"), metadata={"analysis_status": analysis_result.get("status"), "technical_action": tech_detail.action if tech_detail else None, "fundamental_action": fund_detail.action if fund_detail else None, **(extra_metadata or {})})
    except Exception as e:
        report_logger.warning(f"Failed to persist signal for {analysis_result.get('ticker')}: {e}, correlation_id={correlation_id}")


async def _execute_trade(exec_client: ExecutionAgentClient, trade_decision: dict, account_id: Union[int, str], correlation_id: str, db_client: Optional[DatabaseAgentClient] = None) -> dict:
    ticker = trade_decision["symbol"]
    final_verdict = trade_decision["action"]
    quantity = int(trade_decision["position_size"])
    entry_price = trade_decision.get("entry_price", 0)
    try:
        if db_client is not None:
            risk_approval_id = await persist_risk_approval(db_client=db_client, trade_decision=trade_decision, account_id=account_id, correlation_id=correlation_id)
        else:
            if config.TRADING_MODE == "LIVE":
                raise RuntimeError("Database client is required to persist RiskApproval before LIVE execution.")
            risk_approval_id = _ensure_risk_approval_id(trade_decision, correlation_id)
        side = "buy" if "buy" in final_verdict.lower() else "sell"
        order_request = CreateOrderRequest(symbol=ticker, side=side, order_type="market", quantity=quantity, price=float(entry_price), client_order_id=str(uuid.uuid4()), account_id=account_id, risk_approval_id=risk_approval_id, final_quantity=quantity, guard_plan=trade_decision.get("guard_plan"))
        async with exec_client as client:
            response = await client.create_order(order_request, correlation_id)
        if str(response.status).upper() in ["PENDING", "PLACED", "EXECUTED"]:
            return {"status": "submitted", "order_id": response.order_id, "risk_approval_id": risk_approval_id, "details": response.model_dump()}
        return {"status": "rejected", "risk_approval_id": risk_approval_id, "reason": f"Execution Agent returned status: {response.status}"}
    except Exception as e:
        report_logger.exception(f"Trade submission failed for {ticker}: {e}, correlation_id={correlation_id}")
        return {"status": "failed", "risk_approval_id": trade_decision.get("risk_approval_id"), "reason": str(e)}


async def _analyze_single_asset(ticker: str, correlation_id: str) -> dict:
    validate_stock_scope(ticker)
    tech_response, fund_response = await call_agents(ticker, correlation_id)
    tech_raw = _response_to_dict(tech_response)
    fund_raw = _response_to_dict(fund_response)
    tech_detail = _process_agent_response(tech_raw, "technical")
    fund_detail = _process_agent_response(fund_raw, "fundamental")
    if not tech_detail and not fund_detail:
        return {"ticker": ticker, "error": "All agents failed", "raw_data": {"technical": tech_raw, "fundamental": fund_raw}}
    final_verdict = get_weighted_verdict(tech_detail.action if tech_detail else "hold", tech_detail.score if tech_detail else 0.0, fund_detail.action if fund_detail else "hold", fund_detail.score if fund_detail else 0.0, asset_symbol=ticker)
    return {"ticker": ticker, "final_verdict": final_verdict, "status": "complete" if tech_detail and fund_detail else "partial", "details": ReportDetails(technical=tech_detail, fundamental=fund_detail), "raw_data": {"technical": tech_raw, "fundamental": fund_raw}}


def _candidate_to_dict(candidate: Any) -> Dict[str, Any]:
    if isinstance(candidate, dict):
        return candidate
    if hasattr(candidate, "model_dump"):
        return candidate.model_dump(mode="json")
    return {key: getattr(candidate, key) for key in ["symbol", "candidate_score", "confidence_score", "fundamental_score", "technical_score", "discovery_rank", "recommendation", "recommendation_hint", "exchange", "screener", "tags", "reasons", "raw_scores", "metadata"] if hasattr(candidate, key)}


def _scanner_candidate_symbol(candidate: Any) -> Optional[str]:
    return _candidate_to_dict(candidate).get("symbol")


def _scanner_candidate_score(candidate: Any) -> float:
    data = _candidate_to_dict(candidate)
    metadata = data.get("metadata") or {}
    raw_scores = data.get("raw_scores") or metadata.get("raw_scores") or {}
    for value in [data.get("candidate_score"), data.get("confidence_score"), data.get("fundamental_score"), raw_scores.get("fundamental_score") if isinstance(raw_scores, dict) else None, raw_scores.get("quality_score") if isinstance(raw_scores, dict) else None]:
        score = _normalize_score(value)
        if score > 0:
            return score
    try:
        rank = int(data.get("discovery_rank") or metadata.get("discovery_rank"))
        return max(0.1, min(1.0, 1.0 - ((rank - 1) * 0.08))) if rank > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _scanner_candidate_metadata(candidate: Any) -> Dict[str, Any]:
    data = _candidate_to_dict(candidate)
    metadata = data.get("metadata") or {}
    return {"candidate_score": data.get("candidate_score"), "confidence_score": data.get("confidence_score"), "fundamental_score": data.get("fundamental_score"), "technical_score": data.get("technical_score"), "discovery_rank": data.get("discovery_rank") or metadata.get("discovery_rank"), "recommendation": data.get("recommendation"), "recommendation_hint": data.get("recommendation_hint"), "exchange": data.get("exchange") or metadata.get("exchange"), "screener": data.get("screener") or metadata.get("screener"), "tags": data.get("tags") or metadata.get("tags"), "reasons": data.get("reasons") or metadata.get("reasons"), "raw_scores": data.get("raw_scores") or metadata.get("raw_scores"), "metadata": metadata}


def _extract_current_price_and_stop(analysis_result: Dict[str, Any]) -> tuple[float, Any]:
    tech_dict = analysis_result.get("raw_data", {}).get("technical") or {}
    try:
        data = tech_dict.get("data") or {}
        indicators = data.get("indicators") or {}
        return float(data.get("current_price") or 0), indicators.get("stop_loss")
    except Exception:
        return 0.0, None


def _fundamental_v2_scores(analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    data = (analysis_result.get("raw_data", {}).get("fundamental") or {}).get("data") or {}
    composite = _normalize_score(data.get("confidence_score"))
    return {"composite_score": composite, "sector": data.get("sector"), "risk_flags": data.get("risk_flags") or [], "comparative_analysis": data.get("comparative_analysis") or {}}


def _score_deep_analysis(analysis_result: Dict[str, Any], scanner_score: float) -> Dict[str, Any]:
    details = analysis_result.get("details")
    tech_detail = details.technical if details else None
    fund_detail = details.fundamental if details else None
    tech_score = _normalize_score(tech_detail.score if tech_detail else 0.0)
    fund_score = _normalize_score(fund_detail.score if fund_detail else 0.0) or scanner_score
    verdict = analysis_result.get("final_verdict", "hold")
    verdict_score = {"strong_buy": 1.0, "buy": 0.8, "hold": 0.45, "sell": 0.1, "strong_sell": 0.0}.get(str(verdict).lower(), 0.45)
    final_score = (scanner_score * 0.20) + (fund_score * 0.40) + (tech_score * 0.30) + (verdict_score * 0.10)
    return {"scanner_score": round(scanner_score, 4), "technical_score": round(tech_score, 4), "fundamental_score": round(fund_score, 4), "verdict_score": round(verdict_score, 4), "final_opportunity_score": round(final_score, 4)}


async def _run_single_analysis_flow(request: AgentRequestBody, *, dry_run: bool = False) -> StandardAgentResponse:
    correlation_id = str(uuid.uuid4())
    ticker = request.ticker.upper()
    account_id = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    try:
        validate_stock_scope(ticker)
        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await _fetch_context_value(db_client, account_id, correlation_id)
            session_context = await _fetch_session_risk_context(db_client, account_id, ticker, correlation_id)
            analysis_result = await _analyze_single_asset(ticker, correlation_id)
            if "error" in analysis_result:
                raise HTTPException(status_code=500, detail=analysis_result["error"])
            final_verdict = analysis_result["final_verdict"]
            await _persist_signal(db_client, account_id, analysis_result, correlation_id)
            execution_result = {"status": "not_attempted", "reason": "No trade decision."}
            trade_decision = None
            if final_verdict in ["buy", "sell", "strong_buy", "strong_sell"]:
                portfolio_value = balance.cash_balance if balance else 0
                current_position = next((p for p in positions if p.symbol == ticker), None)
                try:
                    validate_trade_action(ticker, final_verdict, current_position)
                except StockGuardError as guard_exc:
                    trade_decision = {"approved": False, "reason": str(guard_exc), "symbol": ticker, "action": final_verdict, "position_size": 0, "session_risk_context": session_context}
                    execution_result = {"status": "rejected", "reason": str(guard_exc)}
                else:
                    entry_price, technical_stop = _extract_current_price_and_stop(analysis_result)
                    trade_decision = assess_trade(portfolio_value=Decimal(portfolio_value), risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")), fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")), enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"), max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")), symbol=ticker, action=final_verdict, entry_price=Decimal(entry_price), technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None, current_position_size=current_position.quantity if current_position else 0, current_symbol_exposure=_position_exposure(current_position), current_total_exposure=_total_position_exposure(positions), open_orders_exposure=context_value, margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)), session_risk_context=session_context)
                    _ensure_risk_approval_id(trade_decision, correlation_id)
                    if dry_run:
                        execution_result = {"status": "dry_run", "reason": "Execution skipped by dry-run mode.", "risk_approval_id": trade_decision.get("risk_approval_id")}
                    elif trade_decision.get("approved"):
                        if config.MANUAL_APPROVAL_REQUIRED:
                            execution_result = {"status": "manual_approval_required", "reason": "Manual approval is required before live stock execution.", "risk_approval_id": trade_decision.get("risk_approval_id")}
                        else:
                            async with ExecutionAgentClient() as exec_client:
                                execution_result = await _execute_trade(exec_client, trade_decision, account_id, correlation_id, db_client=db_client)
                    else:
                        execution_result = {"status": "rejected", "reason": trade_decision.get("reason"), "risk_approval_id": trade_decision.get("risk_approval_id")}
            audit = await _audit_trade_decision(db_client=db_client, account_id=account_id, correlation_id=correlation_id, flow="analyze", symbol=ticker, analysis_result=analysis_result, trade_decision=trade_decision, execution_result=execution_result, context_value=context_value, dry_run=dry_run)
            report = OrchestratorResponse(report_id=correlation_id, ticker=ticker.upper(), timestamp=_now(), final_verdict=final_verdict, status=analysis_result["status"], details=analysis_result["details"])
            learning_state = {"applied": False, "pending": False, "reason": "dry_run" if dry_run else "no_learning_response"}
            if not dry_run:
                learning_client = LearningAgentClient(db_client=db_client)
                learning_response = await learning_client.trigger_learning_cycle(account_id=account_id, symbol=ticker, correlation_id=correlation_id, execution_result=execution_result)
                learning_state = _apply_learning_deltas_if_allowed(learning_response)
            data = report if not dry_run else audit
            return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data=data, metadata=_manager_metadata(risk_context_loaded=True, learning_delta_applied=learning_state["applied"], learning_delta_pending=learning_state["pending"], learning_delta_skipped_reason=learning_state["reason"], dry_run=dry_run))
    except StockGuardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AgentUnavailable as e:
        report_logger.critical(f"An agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/preflight/live", response_model=StandardAgentResponse)
async def stock_live_preflight(account_id: Union[int, str] = None, sample_symbol: str = "AAPL"):
    correlation_id = str(uuid.uuid4())
    account_id = account_id if account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    result = await run_stock_live_preflight(account_id, sample_symbol, correlation_id)
    return StandardAgentResponse(status="success" if result["approved"] else "error", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data=result, metadata=_manager_metadata(risk_context_loaded=result["checks"].get("database", {}).get("status") == "pass"))


@app.get("/health", response_model=StandardAgentResponse)
async def health_check():
    is_healthy = True
    downstream_services = {"database_agent": {"status": "healthy", "details": "Connected successfully."}}
    try:
        async with DatabaseAgentClient() as db_client:
            await db_client.health(correlation_id=str(uuid.uuid4()))
    except Exception as e:
        is_healthy = False
        downstream_services["database_agent"] = {"status": "unhealthy", "details": f"Connection failed: {str(e)}"}
        report_logger.warning(f"Health check failed: Database Agent connection error: {e}")
    content = StandardAgentResponse(status="success" if is_healthy else "error", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data={"dependencies": downstream_services}, metadata=_manager_metadata())
    return JSONResponse(status_code=status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE, content=content.model_dump(mode="json"))


@app.post("/analyze", response_model=StandardAgentResponse)
async def analyze_ticker(request: AgentRequestBody):
    return await _run_single_analysis_flow(request, dry_run=False)


@app.post("/dry-run/analyze", response_model=StandardAgentResponse)
async def dry_run_analyze_ticker(request: AgentRequestBody):
    return await _run_single_analysis_flow(request, dry_run=True)


@app.post("/trade-replay", response_model=StandardAgentResponse)
async def trade_replay(payload: Dict[str, Any]):
    correlation_id = str(uuid.uuid4())
    context_value = _as_decimal((payload.get("risk_context") or {}).get("open_orders_exposure", 0))
    audit = _dry_run_report(correlation_id=correlation_id, flow="trade_replay", symbol=payload.get("symbol"), analysis_result=payload.get("analysis"), trade_decision=payload.get("trade_decision"), execution_result=payload.get("execution"), context_value=context_value, dry_run=True)
    report_logger.info(f"trade_replay_report={_jsonable(audit)}")
    return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data=audit, metadata=_manager_metadata(risk_context_loaded=True, dry_run=True))


async def _process_multi_asset_analysis(tickers: List[str], account_id: Union[int, str], correlation_id: str) -> StandardAgentResponse:
    try:
        tickers = [str(t).upper() for t in tickers]
        for ticker in tickers:
            validate_stock_scope(ticker)
        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await _fetch_context_value(db_client, account_id, correlation_id)
            session_context = await _fetch_session_risk_contexts(db_client, account_id, tickers, correlation_id)
            cash_balance = balance.cash_balance if balance else 0
            analysis_results = await asyncio.gather(*[_analyze_single_asset(ticker, correlation_id) for ticker in tickers])
            valid_results = [res for res in analysis_results if "error" not in res]
            for result in valid_results:
                await _persist_signal(db_client, account_id, result, correlation_id, extra_metadata={"batch": True})
            trade_decisions = assess_portfolio_trades(analysis_results=valid_results, cash_balance=Decimal(cash_balance), existing_positions=positions, per_request_risk_budget=Decimal(config_manager.get("PER_REQUEST_RISK_BUDGET", "0.1")), max_total_exposure=Decimal(config_manager.get("MAX_TOTAL_EXPOSURE", "0.8")), risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE", "0.01")), fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE", "0.1")), enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP", True), max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE", "0.2")), min_position_value=Decimal(config_manager.get("MIN_POSITION_VALUE", "500")), open_orders_exposure=context_value, margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)), session_risk_context=session_context)
            for decision in trade_decisions:
                _ensure_risk_approval_id(decision, correlation_id)
            approved_trades = [d for d in trade_decisions if d.get("approved")]
            execution_outcomes = []
            if approved_trades and not config.MANUAL_APPROVAL_REQUIRED:
                async with ExecutionAgentClient() as exec_client:
                    execution_outcomes = await asyncio.gather(*[_execute_trade(exec_client, decision, account_id, correlation_id, db_client=db_client) for decision in approved_trades])
            elif approved_trades:
                execution_outcomes = [{"status": "manual_approval_required", "reason": "Manual approval is required before live stock execution.", "risk_approval_id": d.get("risk_approval_id")} for d in approved_trades]
            ticker_to_execution = {decision["symbol"]: outcome for decision, outcome in zip(approved_trades, execution_outcomes)}
            ticker_to_decision = {d["symbol"]: d for d in trade_decisions}
            asset_responses = []
            for result in valid_results:
                ticker = result["ticker"]
                analysis_result = AnalysisResult(ticker=ticker, final_verdict=result["final_verdict"], status=result["status"], details=result["details"])
                decision = ticker_to_decision.get(ticker, {"approved": False, "reason": "Not analyzed or verdict was hold.", "symbol": ticker})
                outcome = ticker_to_execution.get(ticker) if decision.get("approved") else None
                exec_status = outcome.get("status", "failed") if outcome else "rejected"
                exec_details = outcome.get("details") if outcome else None
                exec_reason = (outcome.get("reason") if outcome else None) or decision.get("reason", "Reason not provided.")
                await _audit_trade_decision(db_client=db_client, account_id=account_id, correlation_id=correlation_id, flow="analyze_multi", symbol=ticker, analysis_result=result, trade_decision=decision, execution_result={"status": exec_status, "reason": exec_reason, "details": exec_details}, context_value=context_value)
                asset_responses.append(AssetResult(analysis=analysis_result, execution=ExecutionResult(status=exec_status, reason=exec_reason, details=exec_details)))
            total_executed = sum(1 for outcome in execution_outcomes if outcome["status"] == "submitted")
            learning_state = {"applied": False, "pending": False, "reason": "no_approved_trade"}
            if approved_trades and execution_outcomes:
                most_impactful_trade = max(approved_trades, key=lambda t: t.get("risk_amount", 0))
                learning_client = LearningAgentClient(db_client=db_client)
                learning_response = await learning_client.trigger_learning_cycle(account_id=account_id, symbol=most_impactful_trade["symbol"], correlation_id=correlation_id, execution_result=ticker_to_execution.get(most_impactful_trade["symbol"]))
                learning_state = _apply_learning_deltas_if_allowed(learning_response)
            multi_report = MultiOrchestratorResponse(multi_report_id=correlation_id, timestamp=_now(), execution_summary=ExecutionSummary(total_trades_approved=len(approved_trades), total_trades_executed=total_executed, total_trades_failed=len(execution_outcomes) - total_executed), results=asset_responses)
            return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data=multi_report, metadata=_manager_metadata(risk_context_loaded=True, learning_delta_applied=learning_state["applied"], learning_delta_pending=learning_state["pending"], learning_delta_skipped_reason=learning_state["reason"]))
    except StockGuardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AgentUnavailable as e:
        report_logger.critical(f"An agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/analyze-multi", response_model=StandardAgentResponse)
async def analyze_tickers_endpoint(request: MultiAgentRequestBody):
    correlation_id = str(uuid.uuid4())
    account_id = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    return await _process_multi_asset_analysis(request.tickers, account_id, correlation_id)


@app.post("/discover-analyze-trade", response_model=StandardAgentResponse)
async def discover_analyze_trade_endpoint(request: DiscoverAnalyzeTradeRequest):
    correlation_id = str(uuid.uuid4())
    account_id = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    try:
        async with ScannerAgentClient() as scanner_client:
            scan_response = await scanner_client.discover_best_fundamentals(correlation_id=correlation_id, max_universe=request.max_universe, top_n=request.top_n, exchange=request.exchange, max_workers=request.max_workers)
        scan_data = scan_response.data
        scan_payload = scan_data.model_dump() if hasattr(scan_data, "model_dump") else scan_data if isinstance(scan_data, dict) else {}
        candidates = scan_payload.get("candidates", [])
        if not candidates:
            return StandardAgentResponse(status="error", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data={"report_id": correlation_id, "stage": "scanner_discovery", "message": "Scanner returned zero candidates.", "scanner_error": scan_response.error, "scanner_data": scan_payload}, metadata=_manager_metadata(), error={"code": "NO_SCANNER_CANDIDATES", "message": "Scanner returned zero candidates."})
        selected_tickers, ticker_to_scanner_candidate = [], {}
        for candidate in candidates:
            symbol = _scanner_candidate_symbol(candidate)
            if symbol and symbol not in ticker_to_scanner_candidate:
                validate_stock_scope(symbol)
                ticker_to_scanner_candidate[symbol] = candidate
                selected_tickers.append(symbol)
        analysis_results = await asyncio.gather(*[_analyze_single_asset(ticker, correlation_id) for ticker in selected_tickers])
        valid_results = [result for result in analysis_results if "error" not in result]
        if not valid_results:
            return StandardAgentResponse(status="error", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data={"report_id": correlation_id, "stage": "deep_analysis", "scanner_candidates": selected_tickers, "analysis_results": analysis_results}, metadata=_manager_metadata(), error={"code": "NO_VALID_ANALYSIS", "message": "Technical/Fundamental agents returned no valid analysis."})
        ranked = []
        for result in valid_results:
            symbol = result["ticker"]
            scanner_candidate = ticker_to_scanner_candidate.get(symbol)
            score_breakdown = _score_deep_analysis(result, _scanner_candidate_score(scanner_candidate))
            ranked.append({"symbol": symbol, "analysis": result, "scanner_candidate": _scanner_candidate_metadata(scanner_candidate), "score_breakdown": score_breakdown})
        ranked.sort(key=lambda item: item["score_breakdown"]["final_opportunity_score"], reverse=True)
        winner, execution_result, trade_decision = ranked[0], {"status": "not_attempted", "reason": "Execution disabled or score/verdict did not qualify."}, None
        winner_analysis, winner_symbol, winner_score = winner["analysis"], winner["symbol"], winner["score_breakdown"]["final_opportunity_score"]
        async with DatabaseAgentClient() as db_client:
            for item in ranked:
                await _persist_signal(db_client, account_id, item["analysis"], correlation_id, extra_metadata={"flow": "discover_analyze_trade", "scanner_candidate": item["scanner_candidate"], "score_breakdown": item["score_breakdown"], "selected_winner": item["symbol"] == winner_symbol})
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await _fetch_context_value(db_client, account_id, correlation_id)
            session_context = await _fetch_session_risk_context(db_client, account_id, winner_symbol, correlation_id)
            portfolio_value = balance.cash_balance if balance else 0
            current_position = next((p for p in positions if p.symbol == winner_symbol), None)
            entry_price, technical_stop = _extract_current_price_and_stop(winner_analysis)
            final_verdict = winner_analysis.get("final_verdict", "hold")
            eligible_verdict, eligible_score = final_verdict in ["buy", "strong_buy"], winner_score >= request.min_final_score
            if request.execute and eligible_verdict and eligible_score:
                validate_trade_action(winner_symbol, final_verdict, current_position)
                trade_decision = assess_trade(portfolio_value=Decimal(portfolio_value), risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")), fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")), enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"), max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")), symbol=winner_symbol, action=final_verdict, entry_price=Decimal(entry_price), technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None, current_position_size=current_position.quantity if current_position else 0, current_symbol_exposure=_position_exposure(current_position), current_total_exposure=_total_position_exposure(positions), open_orders_exposure=context_value, margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)), session_risk_context=session_context)
                _ensure_risk_approval_id(trade_decision, correlation_id)
                if trade_decision.get("approved"):
                    if config.MANUAL_APPROVAL_REQUIRED:
                        execution_result = {"status": "manual_approval_required", "reason": "Manual approval is required before live stock execution.", "risk_approval_id": trade_decision.get("risk_approval_id")}
                    else:
                        async with ExecutionAgentClient() as exec_client:
                            execution_result = await _execute_trade(exec_client, trade_decision, account_id, correlation_id, db_client=db_client)
                else:
                    execution_result = {"status": "rejected", "reason": trade_decision.get("reason"), "risk_approval_id": trade_decision.get("risk_approval_id")}
            else:
                reason_parts = []
                if not request.execute:
                    reason_parts.append("request.execute=false")
                if not eligible_verdict:
                    reason_parts.append(f"winner verdict is {final_verdict}, not buy/strong_buy")
                if not eligible_score:
                    reason_parts.append(f"winner score {winner_score:.4f} below threshold {request.min_final_score:.4f}")
                execution_result = {"status": "not_attempted", "reason": "; ".join(reason_parts)}
            audit = await _audit_trade_decision(db_client=db_client, account_id=account_id, correlation_id=correlation_id, flow="discover_analyze_trade", symbol=winner_symbol, analysis_result=winner_analysis, trade_decision=trade_decision, execution_result=execution_result, context_value=context_value)
            learning_client = LearningAgentClient(db_client=db_client)
            learning_response = await learning_client.trigger_learning_cycle(account_id=account_id, symbol=winner_symbol, correlation_id=correlation_id, execution_result=execution_result)
            learning_state = _apply_learning_deltas_if_allowed(learning_response)
        data = {"report_id": correlation_id, "flow": "discover_analyze_trade", "scanner_metadata": scan_payload.get("metadata", {}), "scanner_count": len(candidates), "deep_analysis_count": len(valid_results), "top_10_symbols": selected_tickers, "winner": {"symbol": winner_symbol, "final_verdict": winner_analysis.get("final_verdict"), "analysis_status": winner_analysis.get("status"), "score_breakdown": winner["score_breakdown"], "scanner_candidate": winner["scanner_candidate"], "fundamental_v2": _fundamental_v2_scores(winner_analysis)}, "ranked_candidates": [{"rank": index + 1, "symbol": item["symbol"], "final_verdict": item["analysis"].get("final_verdict"), "analysis_status": item["analysis"].get("status"), "score_breakdown": item["score_breakdown"]} for index, item in enumerate(ranked)], "trade_decision": trade_decision, "risk_approval_id": trade_decision.get("risk_approval_id") if trade_decision else None, "execution": execution_result, "dry_run_report": audit}
        return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data=data, metadata=_manager_metadata(risk_context_loaded=True, learning_delta_applied=learning_state["applied"], learning_delta_pending=learning_state["pending"], learning_delta_skipped_reason=learning_state["reason"]))
    except StockGuardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AgentUnavailable as e:
        report_logger.critical(f"An agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        report_logger.exception(f"Discover analyze trade failed: {e}, correlation_id={correlation_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scan-and-analyze", response_model=StandardAgentResponse)
async def scan_and_analyze_endpoint(request: ScanAndAnalyzeRequest):
    correlation_id = str(uuid.uuid4())
    account_id = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    try:
        async with ScannerAgentClient() as scanner_client:
            scan_response = await scanner_client.scan(request.symbols, correlation_id) if request.scan_type == "technical" else await scanner_client.scan_fundamental(request.symbols, correlation_id)
            data = scan_response.data
            if isinstance(data, ScannerResponseData):
                candidates = data.candidates
            elif isinstance(data, dict):
                candidates = data.get("candidates", [])
            else:
                candidates = []
            if request.scan_type == "technical":
                def get_rec(c):
                    return c.recommendation if isinstance(c, ScannerCandidate) else c.get("recommendation")
                candidates.sort(key=lambda x: 2 if get_rec(x) == "STRONG_BUY" else 1, reverse=True)
            def get_symbol(c):
                return c.symbol if isinstance(c, ScannerCandidate) else c.get("symbol")
            selected_tickers = [get_symbol(c) for c in candidates[:request.max_candidates]]
            if not selected_tickers:
                multi_report = MultiOrchestratorResponse(multi_report_id=correlation_id, timestamp=_now(), execution_summary=ExecutionSummary(total_trades_approved=0, total_trades_executed=0, total_trades_failed=0), results=[])
                return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=_now(), data=multi_report, metadata=_manager_metadata())
            return await _process_multi_asset_analysis(selected_tickers, account_id, correlation_id)
    except StockGuardError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AgentUnavailable as e:
        report_logger.critical(f"Scanner Agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        report_logger.exception(f"Scan and analyze failed: {e}, correlation_id={correlation_id}")
        raise HTTPException(status_code=500, detail=str(e))

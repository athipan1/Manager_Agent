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
from .contracts import (
    CreateOrderRequest,
    StandardAgentResponse,
    ScannerResponseData,
    ScannerCandidate,
)
from .resilient_client import AgentUnavailable
from .synthesis import get_weighted_verdict, get_reasons
from .logger import report_logger
from .risk_manager import assess_trade
from .portfolio_risk_manager import assess_portfolio_trades
from .config_manager import config_manager
from .learning_client import LearningAgentClient
from .context_numbers import active_value


app = FastAPI()


@app.get("/health", response_model=StandardAgentResponse)
async def health_check():
    is_healthy = True
    downstream_services = {
        "database_agent": {"status": "healthy", "details": "Connected successfully."},
    }
    try:
        async with DatabaseAgentClient() as db_client:
            await db_client.health(correlation_id=str(uuid.uuid4()))
    except Exception as e:
        is_healthy = False
        downstream_services["database_agent"]["status"] = "unhealthy"
        downstream_services["database_agent"]["details"] = f"Connection failed: {str(e)}"
        report_logger.warning(f"Health check failed: Database Agent connection error: {e}")

    content = StandardAgentResponse(
        status="success" if is_healthy else "error",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={"dependencies": downstream_services},
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=content.model_dump(mode="json"),
    )


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
    resp_dict = _response_to_dict(resp)
    data = resp_dict.get("data") or {}
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
    tech_reason, fund_reason = get_reasons(
        action if agent_type == "technical" else "hold",
        action if agent_type == "fundamental" else "hold",
    )
    return ReportDetail(
        action=action,
        score=score,
        reason=reason or (tech_reason if agent_type == "technical" else fund_reason),
    )


def _as_decimal(value: Any) -> Decimal:
    try:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


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
        response_data = await db_client._get(f"/accounts/{account_id}/orders", correlation_id)
        standard_resp = db_client.validate_standard_response(response_data)
        rows = standard_resp.data or []
        return active_value(rows)
    except Exception as exc:
        if config.TRADING_MODE == "LIVE":
            raise AgentUnavailable(f"Required portfolio context unavailable: {exc}") from exc
        report_logger.warning(f"Portfolio context unavailable in PAPER mode; using zero value. correlation_id={correlation_id}: {exc}")
        return Decimal("0")


async def _persist_signal(
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    analysis_result: dict,
    correlation_id: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        details = analysis_result.get("details")
        tech_detail = details.technical if details else None
        fund_detail = details.fundamental if details else None
        await db_client.save_signal(
            account_id=account_id,
            symbol=analysis_result.get("ticker"),
            correlation_id=correlation_id,
            technical_score=tech_detail.score if tech_detail else None,
            fundamental_score=fund_detail.score if fund_detail else None,
            final_verdict=analysis_result.get("final_verdict"),
            metadata={
                "analysis_status": analysis_result.get("status"),
                "technical_action": tech_detail.action if tech_detail else None,
                "fundamental_action": fund_detail.action if fund_detail else None,
                **(extra_metadata or {}),
            },
        )
    except Exception as e:
        report_logger.warning(f"Failed to persist signal for {analysis_result.get('ticker')}: {e}, correlation_id={correlation_id}")


async def _execute_trade(exec_client: ExecutionAgentClient, trade_decision: dict, account_id: Union[int, str], correlation_id: str) -> dict:
    ticker = trade_decision["symbol"]
    final_verdict = trade_decision["action"]
    quantity = trade_decision["position_size"]
    entry_price = trade_decision.get("entry_price", 0)
    try:
        side = "buy" if "buy" in final_verdict.lower() else "sell"
        order_request = CreateOrderRequest(
            symbol=ticker,
            side=side,
            order_type="market",
            quantity=quantity,
            price=float(entry_price),
            client_order_id=str(uuid.uuid4()),
            account_id=account_id,
        )
        async with exec_client as client:
            response = await client.create_order(order_request, correlation_id)
        if str(response.status).upper() in ["PENDING", "PLACED", "EXECUTED"]:
            return {"status": "submitted", "order_id": response.order_id, "details": response.model_dump()}
        return {"status": "rejected", "reason": f"Execution Agent returned status: {response.status}"}
    except Exception as e:
        report_logger.exception(f"Trade submission failed for {ticker}: {e}, correlation_id={correlation_id}")
        return {"status": "failed", "reason": str(e)}


async def _analyze_single_asset(ticker: str, correlation_id: str) -> dict:
    tech_response, fund_response = await call_agents(ticker, correlation_id)
    tech_raw = _response_to_dict(tech_response)
    fund_raw = _response_to_dict(fund_response)
    tech_detail = _process_agent_response(tech_raw, "technical")
    fund_detail = _process_agent_response(fund_raw, "fundamental")
    if not tech_detail and not fund_detail:
        return {"ticker": ticker, "error": "All agents failed", "raw_data": {"technical": tech_raw, "fundamental": fund_raw}}
    final_verdict = get_weighted_verdict(
        tech_detail.action if tech_detail else "hold",
        tech_detail.score if tech_detail else 0.0,
        fund_detail.action if fund_detail else "hold",
        fund_detail.score if fund_detail else 0.0,
        asset_symbol=ticker,
    )
    return {
        "ticker": ticker,
        "final_verdict": final_verdict,
        "status": "complete" if tech_detail and fund_detail else "partial",
        "details": ReportDetails(technical=tech_detail, fundamental=fund_detail),
        "raw_data": {"technical": tech_raw, "fundamental": fund_raw},
    }


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
    return {
        "candidate_score": data.get("candidate_score"),
        "confidence_score": data.get("confidence_score"),
        "fundamental_score": data.get("fundamental_score"),
        "technical_score": data.get("technical_score"),
        "discovery_rank": data.get("discovery_rank") or metadata.get("discovery_rank"),
        "recommendation": data.get("recommendation"),
        "recommendation_hint": data.get("recommendation_hint"),
        "exchange": data.get("exchange") or metadata.get("exchange"),
        "screener": data.get("screener") or metadata.get("screener"),
        "tags": data.get("tags") or metadata.get("tags"),
        "reasons": data.get("reasons") or metadata.get("reasons"),
        "raw_scores": data.get("raw_scores") or metadata.get("raw_scores"),
        "metadata": metadata,
    }


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


@app.post("/analyze", response_model=StandardAgentResponse)
async def analyze_ticker(request: AgentRequestBody):
    correlation_id = str(uuid.uuid4())
    ticker = request.ticker
    account_id = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    try:
        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await _fetch_context_value(db_client, account_id, correlation_id)
            analysis_result = await _analyze_single_asset(ticker, correlation_id)
            if "error" in analysis_result:
                raise HTTPException(status_code=500, detail=analysis_result["error"])
            final_verdict = analysis_result["final_verdict"]
            await _persist_signal(db_client, account_id, analysis_result, correlation_id)
            execution_result = None
            if final_verdict in ["buy", "sell", "strong_buy", "strong_sell"]:
                portfolio_value = balance.cash_balance if balance else 0
                current_position = next((p for p in positions if p.symbol == ticker), None)
                entry_price, technical_stop = _extract_current_price_and_stop(analysis_result)
                trade_decision = assess_trade(
                    portfolio_value=Decimal(portfolio_value),
                    risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")),
                    fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")),
                    enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"),
                    max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")),
                    symbol=ticker,
                    action=final_verdict,
                    entry_price=Decimal(entry_price),
                    technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None,
                    current_position_size=current_position.quantity if current_position else 0,
                    current_symbol_exposure=_position_exposure(current_position),
                    current_total_exposure=_total_position_exposure(positions),
                    open_orders_exposure=context_value,
                    margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)),
                )
                if trade_decision.get("approved"):
                    async with ExecutionAgentClient() as exec_client:
                        execution_result = await _execute_trade(exec_client, trade_decision, account_id, correlation_id)
                else:
                    execution_result = {"status": "rejected", "reason": trade_decision.get("reason")}
            report = OrchestratorResponse(report_id=correlation_id, ticker=ticker.upper(), timestamp=datetime.datetime.now(datetime.UTC), final_verdict=final_verdict, status=analysis_result["status"], details=analysis_result["details"])
            learning_client = LearningAgentClient(db_client=db_client)
            learning_response = await learning_client.trigger_learning_cycle(account_id=account_id, symbol=ticker, correlation_id=correlation_id, execution_result=execution_result)
            if learning_response and learning_response.learning_state != "warmup":
                deltas = learning_response.policy_deltas.model_dump(exclude_none=True)
                if deltas:
                    config_manager.apply_deltas(deltas)
            return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=datetime.datetime.now(datetime.UTC), data=report)
    except AgentUnavailable as e:
        report_logger.critical(f"An agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))


async def _process_multi_asset_analysis(tickers: List[str], account_id: Union[int, str], correlation_id: str) -> StandardAgentResponse:
    try:
        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await _fetch_context_value(db_client, account_id, correlation_id)
            cash_balance = balance.cash_balance if balance else 0
            analysis_results = await asyncio.gather(*[_analyze_single_asset(ticker, correlation_id) for ticker in tickers])
            valid_results = [res for res in analysis_results if "error" not in res]
            for result in valid_results:
                await _persist_signal(db_client, account_id, result, correlation_id, extra_metadata={"batch": True})
            trade_decisions = assess_portfolio_trades(
                analysis_results=valid_results,
                cash_balance=Decimal(cash_balance),
                existing_positions=positions,
                per_request_risk_budget=Decimal(config_manager.get("PER_REQUEST_RISK_BUDGET", "0.1")),
                max_total_exposure=Decimal(config_manager.get("MAX_TOTAL_EXPOSURE", "0.8")),
                risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE", "0.01")),
                fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE", "0.1")),
                enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP", True),
                max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE", "0.2")),
                min_position_value=Decimal(config_manager.get("MIN_POSITION_VALUE", "500")),
                open_orders_exposure=context_value,
                margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)),
            )
            approved_trades = [d for d in trade_decisions if d.get("approved")]
            async with ExecutionAgentClient() as exec_client:
                execution_outcomes = await asyncio.gather(*[_execute_trade(exec_client, decision, account_id, correlation_id) for decision in approved_trades])
            ticker_to_execution = {decision["symbol"]: outcome for decision, outcome in zip(approved_trades, execution_outcomes)}
            ticker_to_decision = {d["symbol"]: d for d in trade_decisions}
            asset_responses = []
            for result in valid_results:
                ticker = result["ticker"]
                analysis_result = AnalysisResult(ticker=ticker, final_verdict=result["final_verdict"], status=result["status"], details=result["details"])
                decision = ticker_to_decision.get(ticker, {"approved": False, "reason": "Not analyzed or verdict was hold."})
                if decision.get("approved"):
                    outcome = ticker_to_execution.get(ticker) or {"status": "failed"}
                    exec_status = outcome.get("status", "failed")
                    exec_details = outcome.get("details")
                    exec_reason = outcome.get("reason") or decision.get("reason")
                else:
                    exec_status = "rejected"
                    exec_details = None
                    exec_reason = decision.get("reason", "Reason not provided.")
                asset_responses.append(AssetResult(analysis=analysis_result, execution=ExecutionResult(status=exec_status, reason=exec_reason, details=exec_details)))
            total_executed = sum(1 for outcome in execution_outcomes if outcome["status"] == "submitted")
            if approved_trades:
                most_impactful_trade = max(approved_trades, key=lambda t: t.get("risk_amount", 0))
                learning_client = LearningAgentClient(db_client=db_client)
                await learning_client.trigger_learning_cycle(account_id=account_id, symbol=most_impactful_trade["symbol"], correlation_id=correlation_id, execution_result=ticker_to_execution.get(most_impactful_trade["symbol"]))
            multi_report = MultiOrchestratorResponse(multi_report_id=correlation_id, timestamp=datetime.datetime.now(datetime.UTC), execution_summary=ExecutionSummary(total_trades_approved=len(approved_trades), total_trades_executed=total_executed, total_trades_failed=len(execution_outcomes) - total_executed), results=asset_responses)
            return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=datetime.datetime.now(datetime.UTC), data=multi_report)
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
            return StandardAgentResponse(status="error", agent_type="manager-agent", version="1.0.0", timestamp=datetime.datetime.now(datetime.UTC), data={"report_id": correlation_id, "stage": "scanner_discovery", "message": "Scanner returned zero candidates.", "scanner_error": scan_response.error, "scanner_data": scan_payload}, error={"code": "NO_SCANNER_CANDIDATES", "message": "Scanner returned zero candidates."})
        ticker_to_scanner_candidate: Dict[str, Any] = {}
        selected_tickers = []
        for candidate in candidates:
            symbol = _scanner_candidate_symbol(candidate)
            if symbol and symbol not in ticker_to_scanner_candidate:
                ticker_to_scanner_candidate[symbol] = candidate
                selected_tickers.append(symbol)
        analysis_results = await asyncio.gather(*[_analyze_single_asset(ticker, correlation_id) for ticker in selected_tickers])
        valid_results = [result for result in analysis_results if "error" not in result]
        if not valid_results:
            return StandardAgentResponse(status="error", agent_type="manager-agent", version="1.0.0", timestamp=datetime.datetime.now(datetime.UTC), data={"report_id": correlation_id, "stage": "deep_analysis", "scanner_candidates": selected_tickers, "analysis_results": analysis_results}, error={"code": "NO_VALID_ANALYSIS", "message": "Technical/Fundamental agents returned no valid analysis."})
        ranked = []
        for result in valid_results:
            symbol = result["ticker"]
            scanner_candidate = ticker_to_scanner_candidate.get(symbol)
            score_breakdown = _score_deep_analysis(result, _scanner_candidate_score(scanner_candidate))
            ranked.append({"symbol": symbol, "analysis": result, "scanner_candidate": _scanner_candidate_metadata(scanner_candidate), "score_breakdown": score_breakdown})
        ranked.sort(key=lambda item: item["score_breakdown"]["final_opportunity_score"], reverse=True)
        winner = ranked[0]
        winner_analysis = winner["analysis"]
        winner_symbol = winner["symbol"]
        winner_score = winner["score_breakdown"]["final_opportunity_score"]
        execution_result = {"status": "not_attempted", "reason": "Execution disabled or score/verdict did not qualify."}
        trade_decision = None
        async with DatabaseAgentClient() as db_client:
            for item in ranked:
                await _persist_signal(db_client, account_id, item["analysis"], correlation_id, extra_metadata={"flow": "discover_analyze_trade", "scanner_candidate": item["scanner_candidate"], "score_breakdown": item["score_breakdown"], "selected_winner": item["symbol"] == winner_symbol})
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await _fetch_context_value(db_client, account_id, correlation_id)
            portfolio_value = balance.cash_balance if balance else 0
            current_position = next((p for p in positions if p.symbol == winner_symbol), None)
            entry_price, technical_stop = _extract_current_price_and_stop(winner_analysis)
            final_verdict = winner_analysis.get("final_verdict", "hold")
            eligible_verdict = final_verdict in ["buy", "strong_buy"]
            eligible_score = winner_score >= request.min_final_score
            if request.execute and eligible_verdict and eligible_score:
                trade_decision = assess_trade(
                    portfolio_value=Decimal(portfolio_value),
                    risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")),
                    fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")),
                    enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"),
                    max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")),
                    symbol=winner_symbol,
                    action=final_verdict,
                    entry_price=Decimal(entry_price),
                    technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None,
                    current_position_size=current_position.quantity if current_position else 0,
                    current_symbol_exposure=_position_exposure(current_position),
                    current_total_exposure=_total_position_exposure(positions),
                    open_orders_exposure=context_value,
                    margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)),
                )
                if trade_decision.get("approved"):
                    async with ExecutionAgentClient() as exec_client:
                        execution_result = await _execute_trade(exec_client, trade_decision, account_id, correlation_id)
                else:
                    execution_result = {"status": "rejected", "reason": trade_decision.get("reason")}
            else:
                reason_parts = []
                if not request.execute:
                    reason_parts.append("request.execute=false")
                if not eligible_verdict:
                    reason_parts.append(f"winner verdict is {final_verdict}, not buy/strong_buy")
                if not eligible_score:
                    reason_parts.append(f"winner score {winner_score:.4f} below threshold {request.min_final_score:.4f}")
                execution_result = {"status": "not_attempted", "reason": "; ".join(reason_parts)}
            learning_client = LearningAgentClient(db_client=db_client)
            learning_response = await learning_client.trigger_learning_cycle(account_id=account_id, symbol=winner_symbol, correlation_id=correlation_id, execution_result=execution_result)
            if learning_response and learning_response.learning_state != "warmup":
                deltas = learning_response.policy_deltas.model_dump(exclude_none=True)
                if deltas:
                    config_manager.apply_deltas(deltas)
        return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=datetime.datetime.now(datetime.UTC), data={"report_id": correlation_id, "flow": "discover_analyze_trade", "scanner_metadata": scan_payload.get("metadata", {}), "scanner_count": len(candidates), "deep_analysis_count": len(valid_results), "top_10_symbols": selected_tickers, "winner": {"symbol": winner_symbol, "final_verdict": winner_analysis.get("final_verdict"), "analysis_status": winner_analysis.get("status"), "score_breakdown": winner["score_breakdown"], "scanner_candidate": winner["scanner_candidate"], "fundamental_v2": _fundamental_v2_scores(winner_analysis)}, "ranked_candidates": [{"rank": index + 1, "symbol": item["symbol"], "final_verdict": item["analysis"].get("final_verdict"), "analysis_status": item["analysis"].get("status"), "score_breakdown": item["score_breakdown"]} for index, item in enumerate(ranked)], "trade_decision": trade_decision, "execution": execution_result})
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
                multi_report = MultiOrchestratorResponse(multi_report_id=correlation_id, timestamp=datetime.datetime.now(datetime.UTC), execution_summary=ExecutionSummary(total_trades_approved=0, total_trades_executed=0, total_trades_failed=0), results=[])
                return StandardAgentResponse(status="success", agent_type="manager-agent", version="1.0.0", timestamp=datetime.datetime.now(datetime.UTC), data=multi_report)
            return await _process_multi_asset_analysis(selected_tickers, account_id, correlation_id)
    except AgentUnavailable as e:
        report_logger.critical(f"Scanner Agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        report_logger.exception(f"Scan and analyze failed: {e}, correlation_id={correlation_id}")
        raise HTTPException(status_code=500, detail=str(e))

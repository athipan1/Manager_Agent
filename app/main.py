from fastapi import FastAPI, HTTPException
import uuid
import datetime
from typing import List, Union, Dict, Any
from decimal import Decimal

from .models import (
    AgentRequestBody, OrchestratorResponse, ReportDetail, ReportDetails,
    MultiAgentRequestBody, MultiOrchestratorResponse,
    AssetResult, ExecutionSummary, AnalysisResult, ExecutionResult,
    ScanAndAnalyzeRequest
)
from .agent_client import call_agents
from .scanner_client import ScannerAgentClient
from .database_client import DatabaseAgentClient
from .execution_client import ExecutionAgentClient
from .contracts import (
    CreateOrderRequest,
    StandardAgentResponse,
    StandardAgentData
)
from .resilient_client import AgentUnavailable
from .synthesis import get_weighted_verdict, get_reasons
from .logger import report_logger
from .risk_manager import assess_trade
from .portfolio_risk_manager import assess_portfolio_trades
from .config_manager import config_manager
from .learning_client import LearningAgentClient
import asyncio
from fastapi import Depends, status
from fastapi.responses import JSONResponse


app = FastAPI()


@app.get("/health")
async def health_check():
    """
    Health check endpoint for liveness and readiness probes.
    """
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

    if is_healthy:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ok", "dependencies": downstream_services}
        )
    else:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "dependencies": downstream_services}
        )


def _process_agent_response(resp: Union[StandardAgentResponse, Dict[str, Any]], agent_type: str) -> ReportDetail | None:
    """Processes a standardized agent response into a ReportDetail."""
    if not isinstance(resp, StandardAgentResponse):
        return None

    # Analysis agents should return StandardAgentData in the 'data' field
    data_dict = resp.data
    try:
        data = StandardAgentData.model_validate(data_dict)
    except Exception as e:
        report_logger.warning(f"Failed to validate data for {agent_type} agent: {e}")
        return None

    tech_reason, fund_reason = get_reasons(
        data.action if agent_type == "technical" else "hold",
        data.action if agent_type == "fundamental" else "hold"
    )

    return ReportDetail(
        action=data.action,
        score=data.confidence_score,
        reason=data.reason or (tech_reason if agent_type == "technical" else fund_reason)
    )


async def _execute_trade(exec_client: ExecutionAgentClient, trade_decision: dict, account_id: int, correlation_id: str) -> dict:
    """
    Submits a trade to the Execution Agent and returns the outcome.
    """
    ticker = trade_decision['symbol']
    final_verdict = trade_decision['action']
    quantity = trade_decision['position_size']
    entry_price = trade_decision.get('entry_price', 0)

    try:
        order_request = CreateOrderRequest(
            symbol=ticker,
            side=final_verdict,
            quantity=quantity,
            price=float(entry_price),
            client_order_id=str(uuid.uuid4()),
            account_id=account_id
        )

        async with exec_client as client:
            response = await client.create_order(order_request, correlation_id)

        if response.status.upper() in ["PENDING", "PLACED", "EXECUTED"]:
            report_logger.info(
                f"Successfully submitted order for {ticker}. "
                f"Order ID: {response.order_id}, Status: {response.status}, correlation_id={correlation_id}"
            )
            return {
                "status": "submitted",
                "order_id": response.order_id,
                "details": response.model_dump()
            }
        else:
            return {"status": "rejected", "reason": f"Execution Agent returned status: {response.status}"}

    except Exception as e:
        report_logger.exception(f"Trade submission failed for {ticker}: {e}, correlation_id={correlation_id}")
        return {"status": "failed", "reason": str(e)}


async def _analyze_single_asset(ticker: str, correlation_id: str) -> dict:
    """
    Analyzes a single asset.
    """
    tech_response, fund_response = await call_agents(ticker, correlation_id)

    tech_detail = _process_agent_response(tech_response, "technical")
    fund_detail = _process_agent_response(fund_response, "fundamental")

    if not tech_detail and not fund_detail:
        report_logger.error(f"Both agents failed for {ticker}, correlation_id={correlation_id}")
        return {"ticker": ticker, "error": "All agents failed"}

    status = "complete" if tech_detail and fund_detail else "partial"

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
        "status": status,
        "details": ReportDetails(technical=tech_detail, fundamental=fund_detail),
        "raw_data": {"technical": tech_response, "fundamental": fund_response}
    }


@app.post("/analyze", response_model=OrchestratorResponse)
async def analyze_ticker(request: AgentRequestBody):
    """
    Analyzes a ticker and executes a trade if approved.
    """
    correlation_id = str(uuid.uuid4())
    ticker = request.ticker
    account_id = request.account_id if request.account_id is not None else config_manager.get('DEFAULT_ACCOUNT_ID')

    try:
        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)

            analysis_result = await _analyze_single_asset(ticker, correlation_id)
            if "error" in analysis_result:
                raise HTTPException(status_code=500, detail=analysis_result["error"])

            final_verdict = analysis_result["final_verdict"]
            tech_detail = analysis_result["details"].technical
            fund_detail = analysis_result["details"].fundamental

            execution_result = None
            if final_verdict in ["buy", "sell"]:
                portfolio_value = balance.cash_balance if balance else 0
                current_position = next((p for p in positions if p.symbol == ticker), None)
                current_position_size = current_position.quantity if current_position else 0

                # Extract extra info from technical agent if available
                tech_raw = analysis_result["raw_data"]["technical"]
                entry_price = 0
                technical_stop = None
                if isinstance(tech_raw, StandardAgentResponse):
                    try:
                        tech_data = StandardAgentData.model_validate(tech_raw.data)
                        entry_price = tech_data.current_price or 0
                        technical_stop = tech_data.indicators.get("stop_loss") if tech_data.indicators else None
                    except Exception:
                        pass

                trade_decision = assess_trade(
                    portfolio_value=Decimal(portfolio_value),
                    risk_per_trade=Decimal(config_manager.get('RISK_PER_TRADE')),
                    fixed_stop_loss_pct=Decimal(config_manager.get('STOP_LOSS_PERCENTAGE')),
                    enable_technical_stop=config_manager.get('ENABLE_TECHNICAL_STOP'),
                    max_position_pct=Decimal(config_manager.get('MAX_POSITION_PERCENTAGE')),
                    symbol=ticker,
                    action=final_verdict,
                    entry_price=Decimal(entry_price),
                    technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None,
                    current_position_size=current_position_size
                )

                if trade_decision.get("approved"):
                    async with ExecutionAgentClient() as exec_client:
                        execution_result = await _execute_trade(exec_client, trade_decision, account_id, correlation_id)
                else:
                    execution_result = {"status": "rejected", "reason": trade_decision.get('reason')}

            report = OrchestratorResponse(
                report_id=correlation_id,
                ticker=ticker.upper(),
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                final_verdict=final_verdict,
                status=analysis_result["status"],
                details=analysis_result["details"]
            )

            # Auto-Learning Feedback
            learning_client = LearningAgentClient(db_client=db_client)
            learning_response = await learning_client.trigger_learning_cycle(
                account_id=account_id,
                symbol=ticker,
                correlation_id=correlation_id,
                execution_result=execution_result,
            )

            if learning_response and learning_response.learning_state != "warmup":
                deltas = learning_response.policy_deltas.model_dump(exclude_none=True)
                if deltas:
                    config_manager.apply_deltas(deltas)

            return report

    except AgentUnavailable as e:
        report_logger.critical(f"An agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))

async def _process_multi_asset_analysis(tickers: List[str], account_id: int, correlation_id: str) -> MultiOrchestratorResponse:
    """
    Internal logic for analyzing multiple assets and managing portfolio risk.
    """
    try:
        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)

            cash_balance = balance.cash_balance if balance else 0
            positions_value = sum(p.quantity * (p.current_market_price or p.average_cost) for p in positions)
            portfolio_value = cash_balance + positions_value

            analysis_tasks = [_analyze_single_asset(ticker, correlation_id) for ticker in tickers]
            analysis_results = await asyncio.gather(*analysis_tasks)
            valid_results = [res for res in analysis_results if "error" not in res]

            trade_decisions = assess_portfolio_trades(
                analysis_results=valid_results,
                cash_balance=Decimal(cash_balance),
                existing_positions=positions,
                per_request_risk_budget=Decimal(config_manager.get('PER_REQUEST_RISK_BUDGET', '0.1')),
                max_total_exposure=Decimal(config_manager.get('MAX_TOTAL_EXPOSURE', '0.8')),
                risk_per_trade=Decimal(config_manager.get('RISK_PER_TRADE', '0.01')),
                fixed_stop_loss_pct=Decimal(config_manager.get('STOP_LOSS_PERCENTAGE', '0.1')),
                enable_technical_stop=config_manager.get('ENABLE_TECHNICAL_STOP', True),
                max_position_pct=Decimal(config_manager.get('MAX_POSITION_PERCENTAGE', '0.2')),
                min_position_value=Decimal(config_manager.get('MIN_POSITION_VALUE', '500')),
            )

            approved_trades = [d for d in trade_decisions if d.get('approved')]

            async with ExecutionAgentClient() as exec_client:
                execution_tasks = [_execute_trade(exec_client, decision, account_id, correlation_id) for decision in approved_trades]
                execution_outcomes = await asyncio.gather(*execution_tasks)

            ticker_to_execution = {decision['symbol']: outcome for decision, outcome in zip(approved_trades, execution_outcomes)}
            ticker_to_decision = {d['symbol']: d for d in trade_decisions}

            asset_responses = []
            for result in valid_results:
                ticker = result['ticker']
                analysis_result = AnalysisResult(
                    ticker=ticker,
                    final_verdict=result["final_verdict"],
                    status=result["status"],
                    details=result["details"],
                )

                decision = ticker_to_decision.get(ticker, {'approved': False, 'reason': 'Not analyzed or verdict was hold.'})
                exec_status = "not_attempted"
                exec_reason = None
                exec_details = None

                if decision.get('approved'):
                    outcome = ticker_to_execution.get(ticker)
                    exec_status = outcome.get('status', 'failed') if outcome else 'failed'
                    exec_details = outcome.get('details')
                    exec_reason = f"Assessment: {decision.get('reason')}. Execution: {outcome.get('reason')}" if outcome and outcome.get('reason') else decision.get('reason')
                else:
                    exec_status = "rejected"
                    exec_reason = decision.get('reason', 'Reason not provided.')

                asset_responses.append(AssetResult(analysis=analysis_result, execution=ExecutionResult(status=exec_status, reason=exec_reason, details=exec_details)))

            total_executed = sum(1 for outcome in execution_outcomes if outcome['status'] == 'submitted')

            # Auto-Learning Feedback
            if approved_trades:
                most_impactful_trade = max(approved_trades, key=lambda t: t.get('risk_amount', 0))
                learning_client = LearningAgentClient(db_client=db_client)
                await learning_client.trigger_learning_cycle(
                    account_id=account_id,
                    symbol=most_impactful_trade['symbol'],
                    correlation_id=correlation_id,
                    execution_result=ticker_to_execution.get(most_impactful_trade['symbol'])
                )

            return MultiOrchestratorResponse(
                multi_report_id=correlation_id,
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                execution_summary=ExecutionSummary(
                    total_trades_approved=len(approved_trades),
                    total_trades_executed=total_executed,
                    total_trades_failed=len(execution_outcomes) - total_executed
                ),
                results=asset_responses
            )
    except AgentUnavailable as e:
        report_logger.critical(f"An agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/analyze-multi", response_model=MultiOrchestratorResponse)
async def analyze_tickers_endpoint(request: MultiAgentRequestBody):
    """
    Analyzes multiple tickers and manages portfolio risk.
    """
    correlation_id = str(uuid.uuid4())
    account_id = request.account_id if request.account_id is not None else config_manager.get('DEFAULT_ACCOUNT_ID')
    return await _process_multi_asset_analysis(request.tickers, account_id, correlation_id)


@app.post("/scan-and-analyze", response_model=MultiOrchestratorResponse)
async def scan_and_analyze_endpoint(request: ScanAndAnalyzeRequest):
    """
    Scans for potential candidates and then performs multi-asset analysis on them.
    """
    correlation_id = str(uuid.uuid4())
    account_id = request.account_id if request.account_id is not None else config_manager.get('DEFAULT_ACCOUNT_ID')

    try:
        async with ScannerAgentClient() as scanner_client:
            if request.scan_type == "technical":
                scan_response = await scanner_client.scan(request.symbols, correlation_id)
                candidates = scan_response.data.get("candidates", []) if scan_response.data else []
                # Simple ranking: STRONG_BUY first, then BUY
                candidates.sort(key=lambda x: 2 if x.get("recommendation") == "STRONG_BUY" else 1, reverse=True)
            else:
                scan_response = await scanner_client.scan_fundamental(request.symbols, correlation_id)
                candidates = scan_response.data.get("candidates", []) if scan_response.data else []
                # Already ranked by fundamental_score in Scanner_Agent

            selected_tickers = [c["symbol"] for c in candidates[:request.max_candidates]]

            if not selected_tickers:
                report_logger.info(f"No candidates found by scanner for scan_type={request.scan_type}, correlation_id={correlation_id}")
                return MultiOrchestratorResponse(
                    multi_report_id=correlation_id,
                    timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                    execution_summary=ExecutionSummary(
                        total_trades_approved=0,
                        total_trades_executed=0,
                        total_trades_failed=0
                    ),
                    results=[]
                )

            report_logger.info(f"Scanner found {len(selected_tickers)} candidates: {selected_tickers}, correlation_id={correlation_id}")
            return await _process_multi_asset_analysis(selected_tickers, account_id, correlation_id)

    except AgentUnavailable as e:
        report_logger.critical(f"Scanner Agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        report_logger.exception(f"Scan and analyze failed: {e}, correlation_id={correlation_id}")
        raise HTTPException(status_code=500, detail=str(e))

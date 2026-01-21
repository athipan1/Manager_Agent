from fastapi import FastAPI, HTTPException
import uuid
import datetime
from typing import List
from decimal import Decimal

from .models import (
    AgentRequestBody, OrchestratorResponse, ReportDetail, ReportDetails,
    MultiAgentRequestBody, MultiOrchestratorResponse,
    AssetResult, ExecutionSummary, AnalysisResult, ExecutionResult
)
from .agent_client import call_agents
from .adapters.service import normalize_response
from .adapters.database import normalize_database_response
from .database_client import DatabaseAgentClient
from .execution_client import ExecutionAgentClient
from .models import CreateOrderRequest
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
from .resilient_client import ResilientAgentClient


app = FastAPI()


@app.get("/health")
async def health_check():
    """
    Health check endpoint for liveness and readiness probes.
    Checks connectivity to critical downstream services.
    """
    # Liveness is implicitly checked by the service responding.
    is_healthy = True
    downstream_services = {
        "database_agent": {"status": "healthy", "details": "Connected successfully."},
        # In a real system, you'd add other critical services here.
    }

    # Readiness: Check connection to the Database Agent
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


async def _execute_trade(exec_client: ExecutionAgentClient, trade_decision: dict, account_id: int, correlation_id: str) -> dict:
    """
    Submits a trade to the Execution Agent and returns the outcome.
    """
    ticker = trade_decision['symbol']
    final_verdict = trade_decision['action']
    quantity = trade_decision['position_size']
    entry_price = trade_decision.get('entry_price', 0)

    try:
        # 1. Prepare data for Execution Agent
        order_request = CreateOrderRequest(
            symbol=ticker,
            side=final_verdict,
            quantity=quantity,
            price=entry_price,
            client_order_id=uuid.uuid4()
        )

        # 2. Call the Execution Agent
        async with exec_client as client:
            response = await client.create_order(order_request, correlation_id)

        # 3. Handle response (accepting PENDING/PLACED as success)
        if isinstance(response, dict) or not response:
            reason = response.get("reason", "Unknown error from Execution Agent")
            report_logger.error(f"Failed to submit order for {ticker}: {reason}, correlation_id={correlation_id}")
            return {"status": "failed", "reason": reason}

        if response.status.upper() in ["PENDING", "PLACED"]:
            report_logger.info(
                f"Successfully submitted order for {ticker}. "
                f"Execution Agent Order ID: {response.order_id}, "
                f"Client Order ID: {response.client_order_id}, "
                f"Status: {response.status}, correlation_id={correlation_id}"
            )
            # Return a structure consistent with the original function's success case
            return {
                "status": "submitted", # Renamed from "executed"
                "order_id": response.order_id,
                "details": response.model_dump()
            }
        else:
            report_logger.warning(
                f"Order for {ticker} was not accepted by Execution Agent. "
                f"Status: {response.status}, correlation_id={correlation_id}"
            )
            return {"status": "rejected", "reason": f"Execution Agent returned status: {response.status}"}

    except Exception as e:
        report_logger.exception(f"Trade submission failed for {ticker}: {e}, correlation_id={correlation_id}")
        return {"status": "failed", "reason": str(e)}


async def _analyze_single_asset(ticker: str, correlation_id: str) -> dict:
    """
    Analyzes a single asset by calling agents, normalizing data, and synthesizing a verdict.
    This function will be called concurrently for multiple assets.
    """
    # 2. Call analysis agents concurrently
    tech_response_raw, fund_response_raw = await call_agents(ticker, correlation_id)

    # 3. Normalize agent responses to the canonical model
    normalized_tech = normalize_response(tech_response_raw)
    normalized_fund = normalize_response(fund_response_raw)

    if not normalized_tech and not normalized_fund:
        report_logger.error(f"Both agents failed for {ticker}, correlation_id={correlation_id}")
        # Return a sentinel value or specific error structure
        return {"ticker": ticker, "error": "All agents failed"}

    # 4. Construct report details from canonical responses
    tech_detail = None
    if normalized_tech:
        tech_reason, _ = get_reasons(normalized_tech.data.action, "hold")
        tech_detail = ReportDetail(
            action=normalized_tech.data.action,
            score=normalized_tech.data.confidence_score,
            reason=tech_reason
        )

    fund_detail = None
    if normalized_fund:
        _, fund_reason = get_reasons("hold", normalized_fund.data.action)
        fund_detail = ReportDetail(
            action=normalized_fund.data.action,
            score=normalized_fund.data.confidence_score,
            reason=fund_reason
        )

    status = "complete" if tech_detail and fund_detail else "partial"

    # 5. Get final verdict
    final_verdict = get_weighted_verdict(
        tech_detail.action if tech_detail else "hold",
        tech_detail.score if tech_detail else 0.0,
        fund_detail.action if fund_detail else "hold",
        fund_detail.score if fund_detail else 0.0,
        asset_symbol=ticker,
    )

    # This dictionary will be enhanced with risk assessment and execution details later
    return {
        "ticker": ticker,
        "final_verdict": final_verdict,
        "status": status,
        "details": ReportDetails(technical=tech_detail, fundamental=fund_detail),
        "raw_data": {"technical": normalized_tech, "fundamental": normalized_fund}
    }


@app.post("/analyze", response_model=OrchestratorResponse)
async def analyze_ticker(request: AgentRequestBody):
    """
    Receives a ticker, gets account info, queries agents, returns a report,
    and executes a trade based on the final verdict.
    """
    correlation_id = str(uuid.uuid4())
    ticker = request.ticker
    account_id = request.account_id if request.account_id is not None else config_manager.get('DEFAULT_ACCOUNT_ID')

    try:
        async with DatabaseAgentClient() as db_client:
            # 1. Get current financial status from Database Agent
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            report_logger.info(
                f"Initial state: Balance: {balance.cash_balance if balance else 'N/A'}, "
                f"Positions: {[p.symbol for p in positions]}, correlation_id={correlation_id}"
            )

            # 2. Call analysis agents concurrently
            tech_response_raw, fund_response_raw = await call_agents(ticker, correlation_id)

            # 3. Normalize agent responses to the canonical model
            normalized_tech = normalize_response(tech_response_raw)
            normalized_fund = normalize_response(fund_response_raw)

            if not normalized_tech and not normalized_fund:
                report_logger.error(f"Both agents failed to provide a valid, normalizable response, correlation_id={correlation_id}")
                raise HTTPException(status_code=500, detail="Both Technical and Fundamental Agents failed to provide valid responses.")

            # 4. Construct report details from canonical responses
            tech_detail = None
            if normalized_tech:
                tech_reason, _ = get_reasons(normalized_tech.data.action, "hold")
                tech_detail = ReportDetail(
                    action=normalized_tech.data.action,
                    score=normalized_tech.data.confidence_score,
                    reason=tech_reason
                )

            fund_detail = None
            if normalized_fund:
                _, fund_reason = get_reasons("hold", normalized_fund.data.action)
                fund_detail = ReportDetail(
                    action=normalized_fund.data.action,
                    score=normalized_fund.data.confidence_score,
                    reason=fund_reason
                )

            status = "complete" if tech_detail and fund_detail else "partial"

            # 5. Get final verdict
            final_verdict = get_weighted_verdict(
                tech_detail.action if tech_detail else "hold",
                tech_detail.score if tech_detail else 0.0,
                fund_detail.action if fund_detail else "hold",
                fund_detail.score if fund_detail else 0.0,
                asset_symbol=ticker,
            )

            # 6. Execute trade based on verdict
            execution_result = None
            if final_verdict in ["buy", "sell"]:
                portfolio_value = balance.cash_balance if balance else 0
                current_position = next((p for p in positions if p.symbol == ticker), None)
                current_position_size = current_position.quantity if current_position else 0

                entry_price = normalized_tech.data.current_price if (normalized_tech and hasattr(normalized_tech.data, 'current_price')) else 0
                technical_stop = normalized_tech.data.indicators.get("stop_loss") if (normalized_tech and hasattr(normalized_tech.data, 'indicators')) else None

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

                report_logger.info(f"Risk Manager Decision: {trade_decision}")

                if trade_decision.get("approved"):
                    async with ExecutionAgentClient() as exec_client:
                        execution_result = await _execute_trade(exec_client, trade_decision, account_id, correlation_id)
                else:
                    report_logger.warning(f"Trade for {ticker} rejected by Risk Manager: {trade_decision.get('reason')}, correlation_id={correlation_id}")
                    execution_result = {"status": "rejected", "reason": trade_decision.get('reason')}

            # 7. Construct and log the final report
            report = OrchestratorResponse(
                report_id=correlation_id,  # Use correlation_id as the report_id for consistency
                ticker=ticker.upper(),
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                final_verdict=final_verdict,
                status=status,
                details=ReportDetails(technical=tech_detail, fundamental=fund_detail)
            )

            report_logger.info({
                "ticker": report.ticker, "final_verdict": report.final_verdict,
                "status": report.status, "report_id": report.report_id
            })

            # --- Auto-Learning Feedback Loop ---
            # The client now acts as an adapter, handling data gathering internally.
            learning_client = LearningAgentClient(db_client=db_client)
            learning_response = await learning_client.trigger_learning_cycle(
                account_id=account_id,
                symbol=ticker,
                correlation_id=correlation_id,
                execution_result=execution_result,
            )

            if learning_response and learning_response.learning_state != "warmup":
                if learning_response.policy_deltas:
                    deltas = learning_response.policy_deltas.model_dump(exclude_none=True)
                    if deltas:  # Ensure there are actually deltas to apply
                        config_manager.apply_deltas(deltas)
                        report_logger.info(f"Applied new policy deltas: {deltas}, correlation_id={correlation_id}")
            # --- End of Feedback Loop ---

            return report

    except AgentUnavailable as e:
        report_logger.critical(f"An agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=f"A required agent service is currently unavailable: {e}")

@app.post("/analyze-multi", response_model=MultiOrchestratorResponse)
async def analyze_tickers_endpoint(request: MultiAgentRequestBody):
    """
    Receives a list of tickers, analyzes them concurrently, applies portfolio-level
    risk management, and executes trades.
    """
    correlation_id = str(uuid.uuid4())
    account_id = request.account_id if request.account_id is not None else config_manager.get('DEFAULT_ACCOUNT_ID')

    try:
        async with DatabaseAgentClient() as db_client:
            # --- Get portfolio context ---
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)

            # --- Correct portfolio value calculation ---
            cash_balance = balance.cash_balance if balance else 0
            positions_value = sum(p.quantity * (p.current_market_price or p.average_cost) for p in positions)
            portfolio_value = cash_balance + positions_value

            # --- Step 1: Concurrent Analysis ---
            analysis_tasks = [_analyze_single_asset(ticker, correlation_id) for ticker in request.tickers]
            analysis_results = await asyncio.gather(*analysis_tasks)
            valid_results = [res for res in analysis_results if "error" not in res]

            # --- Step 2: Portfolio Risk Assessment ---
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

            # --- Step 3: Independent Trade Execution ---
            approved_trades = [d for d in trade_decisions if d.get('approved')]

            async with ExecutionAgentClient() as exec_client:
                execution_tasks = [_execute_trade(exec_client, decision, account_id, correlation_id) for decision in approved_trades]
                execution_outcomes = await asyncio.gather(*execution_tasks)

            # --- Final Response Construction ---
            ticker_to_execution = {decision['symbol']: outcome for decision, outcome in zip(approved_trades, execution_outcomes)}
            ticker_to_decision = {d['symbol']: d for d in trade_decisions}

            asset_responses = []
            for result in valid_results:
                ticker = result['ticker']

                # 1. Create AnalysisResult
                analysis_result = AnalysisResult(
                    ticker=ticker,
                    final_verdict=result["final_verdict"],
                    status=result["status"],
                    details=result["details"],
                )

                # 2. Determine ExecutionResult
                decision = ticker_to_decision.get(ticker, {'approved': False, 'reason': 'Not analyzed or verdict was hold.'})

                exec_status = "not_attempted"
                exec_reason = None
                exec_details = None

                if decision.get('approved'):
                    outcome = ticker_to_execution.get(ticker)
                    exec_status = outcome.get('status', 'failed') if outcome else 'failed'
                    exec_details = outcome.get('details')

                    assessment_reason = decision.get('reason')
                    execution_reason_from_outcome = outcome.get('reason') if outcome else None

                    if assessment_reason and execution_reason_from_outcome:
                        exec_reason = f"Assessment: {assessment_reason}. Execution: {execution_reason_from_outcome}"
                    else:
                        exec_reason = assessment_reason or execution_reason_from_outcome

                else:  # Not approved by risk manager
                    exec_status = "rejected"
                    exec_reason = decision.get('reason', 'Reason not provided.')

                execution_result = ExecutionResult(
                    status=exec_status,
                    reason=exec_reason,
                    details=exec_details
                )

                # 3. Combine into AssetResult
                asset_responses.append(AssetResult(
                    analysis=analysis_result,
                    execution=execution_result,
                ))

            total_executed = sum(1 for outcome in execution_outcomes if outcome['status'] == 'submitted')
            total_failed = len(execution_outcomes) - total_executed

            # --- Auto-Learning Feedback Loop ---
            if approved_trades:
                # Find the most impactful trade (for selecting the symbol)
                most_impactful_trade_decision = max(approved_trades, key=lambda t: t.get('risk_amount', 0))
                learning_ticker = most_impactful_trade_decision['symbol']

                # Find the corresponding execution outcome for that trade
                most_impactful_execution_outcome = ticker_to_execution.get(learning_ticker)

                learning_client = LearningAgentClient(db_client=db_client)
                learning_response = await learning_client.trigger_learning_cycle(
                    account_id=account_id,
                    symbol=learning_ticker,
                    correlation_id=correlation_id,
                    execution_result=most_impactful_execution_outcome
                )
                if learning_response and learning_response.policy_deltas:
                    deltas = learning_response.policy_deltas.model_dump(exclude_none=True)
                    if deltas:
                        config_manager.apply_deltas(deltas)
                        report_logger.info(f"Applied new policy deltas from multi-asset cycle: {deltas}, correlation_id={correlation_id}")

            return MultiOrchestratorResponse(
                multi_report_id=correlation_id,
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                execution_summary=ExecutionSummary(
                    total_trades_approved=len(approved_trades),
                    total_trades_executed=total_executed,
                    total_trades_failed=total_failed
                ),
                results=asset_responses
            )

    except AgentUnavailable as e:
        report_logger.critical(f"An agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail=f"A required agent service is currently unavailable: {e}")

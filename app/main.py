from fastapi import FastAPI, HTTPException
import uuid
import datetime
from typing import List

from .models import (
    AgentRequestBody, OrchestratorResponse, ReportDetail, ReportDetails,
    CreateOrderBody, MultiAgentRequestBody, MultiOrchestratorResponse,
    AssetAnalysisResult, ExecutionSummary
)
from .agent_client import call_agents
from .adapters.service import normalize_response
from .database_client import DatabaseAgentClient, DatabaseAgentUnavailable
from .synthesis import get_weighted_verdict, get_reasons
from .logger import report_logger
from .risk_manager import assess_trade
from .portfolio_risk_manager import assess_portfolio_trades
from .config_manager import config_manager
from .learning_client import LearningAgentClient
import asyncio


app = FastAPI()


async def _execute_trade(db_client: DatabaseAgentClient, trade_decision: dict, account_id: int, correlation_id: str) -> dict:
    """
    Executes a single trade and returns the outcome.
    """
    ticker = trade_decision['symbol']
    final_verdict = trade_decision['action']
    quantity = trade_decision['position_size']
    # NOTE: Entry price might need to be sourced more reliably for sells
    entry_price = trade_decision.get('entry_price', 0)

    try:
        order_body = CreateOrderBody(symbol=ticker, order_type=final_verdict.upper(), quantity=quantity, price=entry_price)
        new_order_response = await db_client.create_order(account_id, order_body, correlation_id)

        if not new_order_response or new_order_response.status != "pending":
            raise Exception("Failed to create trade order.")

        order_id = new_order_response.order_id
        report_logger.info(f"Created order {order_id} to {final_verdict} {quantity} {ticker} @ {entry_price}, correlation_id={correlation_id}")

        executed_order = await db_client.execute_order(order_id, correlation_id)
        if not executed_order or executed_order.status != "executed":
            raise Exception("Failed to execute order.")

        report_logger.info(f"Successfully executed order {executed_order.order_id}, correlation_id={correlation_id}")
        return {"status": "executed", "order_id": executed_order.order_id, "details": executed_order.model_dump()}

    except Exception as e:
        report_logger.error(f"Trade execution failed for {ticker}: {e}, correlation_id={correlation_id}")
        return {"status": "failed", "reason": str(e)}


async def _analyze_single_asset(ticker: str, correlation_id: str) -> dict:
    """
    Analyzes a single asset by calling agents, normalizing data, and synthesizing a verdict.
    This function will be called concurrently for multiple assets.
    """
    # 2. Call analysis agents concurrently
    tech_response_raw, fund_response_raw = await call_agents(ticker)

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
    account_id = 1  # Using a fixed account ID as per original logic

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
            tech_response_raw, fund_response_raw = await call_agents(ticker)

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
            )

            # 6. Execute trade based on verdict
            if final_verdict in ["buy", "sell"]:
                portfolio_value = balance.cash_balance if balance else 0
                current_position = next((p for p in positions if p.symbol == ticker), None)
                current_position_size = current_position.quantity if current_position else 0

                entry_price = normalized_tech.data.current_price if (normalized_tech and hasattr(normalized_tech.data, 'current_price')) else 0
                technical_stop = normalized_tech.data.indicators.get("stop_loss") if (normalized_tech and hasattr(normalized_tech.data, 'indicators')) else None

                trade_decision = assess_trade(
                    portfolio_value=portfolio_value,
                    risk_per_trade=config_manager.get('RISK_PER_TRADE'),
                    fixed_stop_loss_pct=config_manager.get('STOP_LOSS_PERCENTAGE'),
                    enable_technical_stop=config_manager.get('ENABLE_TECHNICAL_STOP'),
                    max_position_pct=config_manager.get('MAX_POSITION_PERCENTAGE'),
                    symbol=ticker,
                    action=final_verdict,
                    entry_price=entry_price,
                    technical_stop_loss=technical_stop,
                    current_position_size=current_position_size
                )

                report_logger.info(f"Risk Manager Decision: {trade_decision}")

                if trade_decision.get("approved"):
                    quantity = trade_decision["position_size"]
                    order_body = CreateOrderBody(symbol=ticker, order_type=final_verdict.upper(), quantity=quantity, price=entry_price)
                    new_order_response = await db_client.create_order(account_id, order_body, correlation_id)

                    if new_order_response and new_order_response.status == "pending":
                        order_id = new_order_response.order_id
                        report_logger.info(f"Created order {order_id} to {final_verdict} {quantity} {ticker} @ {entry_price}, correlation_id={correlation_id}")
                        executed_order = await db_client.execute_order(order_id, correlation_id)
                        if executed_order and executed_order.status == "executed":
                            report_logger.info(f"Successfully executed order {executed_order.order_id}, correlation_id={correlation_id}")
                        else:
                            report_logger.error(f"Failed to execute order {order_id}, correlation_id={correlation_id}")
                    else:
                        report_logger.error(f"Failed to create trade order, correlation_id={correlation_id}")
                else:
                    report_logger.warning(f"Trade for {ticker} rejected by Risk Manager: {trade_decision.get('reason')}, correlation_id={correlation_id}")

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
                correlation_id=correlation_id
            )

            if learning_response and learning_response.learning_state != "warmup":
                if learning_response.policy_deltas:
                    deltas = learning_response.policy_deltas.model_dump(exclude_none=True)
                    if deltas:  # Ensure there are actually deltas to apply
                        config_manager.apply_deltas(deltas)
                        report_logger.info(f"Applied new policy deltas: {deltas}, correlation_id={correlation_id}")
            # --- End of Feedback Loop ---

            return report

    except DatabaseAgentUnavailable as e:
        report_logger.critical(f"Database Agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail="The Database Agent service is currently unavailable.")

@app.post("/analyze-multi", response_model=MultiOrchestratorResponse)
async def analyze_tickers_endpoint(request: MultiAgentRequestBody):
    """
    Receives a list of tickers, analyzes them concurrently, applies portfolio-level
    risk management, and executes trades.
    """
    correlation_id = str(uuid.uuid4())
    account_id = 1  # Fixed account ID

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
                portfolio_value=portfolio_value,
                existing_positions=positions,
                per_request_risk_budget=config_manager.get('PER_REQUEST_RISK_BUDGET'),
                max_total_exposure=config_manager.get('MAX_TOTAL_EXPOSURE'),
                risk_per_trade=config_manager.get('RISK_PER_TRADE'),
                fixed_stop_loss_pct=config_manager.get('STOP_LOSS_PERCENTAGE'),
                enable_technical_stop=config_manager.get('ENABLE_TECHNICAL_STOP'),
                max_position_pct=config_manager.get('MAX_POSITION_PERCENTAGE'),
                min_position_value=config_manager.get('MIN_POSITION_VALUE'),
            )

            # --- Step 3: Independent Trade Execution ---
            approved_trades = [d for d in trade_decisions if d.get('approved')]
            execution_tasks = [_execute_trade(db_client, decision, account_id, correlation_id) for decision in approved_trades]
            execution_outcomes = await asyncio.gather(*execution_tasks)

            # --- Final Response Construction ---
            ticker_to_execution = {decision['symbol']: outcome for decision, outcome in zip(approved_trades, execution_outcomes)}
            ticker_to_decision = {d['symbol']: d for d in trade_decisions}

            asset_responses = []
            for result in valid_results:
                ticker = result['ticker']
                decision = ticker_to_decision.get(ticker, {'approved': False, 'reason': 'Not analyzed or verdict was hold.'})

                execution_status = "not_attempted"
                execution_details = None

                if decision.get('approved'):
                    outcome = ticker_to_execution.get(ticker)
                    execution_status = outcome['status']
                    execution_details = outcome
                else:
                    execution_status = "rejected"
                    execution_details = {"reason": decision.get('reason')}

                asset_responses.append(AssetAnalysisResult(
                    ticker=ticker,
                    final_verdict=result["final_verdict"],
                    status=result["status"],
                    details=result["details"],
                    execution_status=execution_status,
                    execution_details=execution_details
                ))

            total_executed = sum(1 for outcome in execution_outcomes if outcome['status'] == 'executed')
            total_failed = len(execution_outcomes) - total_executed

            # --- Auto-Learning Feedback Loop ---
            if approved_trades:
                most_impactful_trade = max(approved_trades, key=lambda t: t.get('risk_amount', 0))
                learning_ticker = most_impactful_trade['symbol']

                learning_client = LearningAgentClient(db_client=db_client)
                learning_response = await learning_client.trigger_learning_cycle(
                    account_id=account_id,
                    symbol=learning_ticker,
                    correlation_id=correlation_id
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

    except DatabaseAgentUnavailable as e:
        report_logger.critical(f"Database Agent is unavailable: {e}")
        raise HTTPException(status_code=503, detail="The Database Agent service is currently unavailable.")

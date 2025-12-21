from fastapi import FastAPI, HTTPException
import uuid
import datetime

from .models import (
    AgentRequestBody, OrchestratorResponse, ReportDetail, ReportDetails,
    TechnicalAgentResponse, FundamentalAgentResponse, CreateOrderBody, CreateOrderResponse
)
from .agent_client import call_agents
from .database_client import get_account_balance, get_positions, create_order, execute_order
from .synthesis import get_weighted_verdict, get_reasons
from .logger import report_logger
from .risk_manager import assess_trade
from . import config

app = FastAPI()

@app.post("/analyze", response_model=OrchestratorResponse)
async def analyze_ticker(request: AgentRequestBody):
    """
    Receives a ticker, gets account info, queries agents, returns a report,
    and executes a trade based on the final verdict.
    """
    ticker = request.ticker

    # 1. Get current financial status from Database Agent
    balance = await get_account_balance()
    positions = await get_positions()
    report_logger.info(f"Initial state: Balance: {balance.cash_balance if balance else 'N/A'}, Positions: {[p.symbol for p in positions]}")

    # 2. Call analysis agents concurrently
    tech_response_raw, fund_response_raw = await call_agents(ticker)

    # 3. Handle potential errors from agents
    tech_error = isinstance(tech_response_raw, Exception) or "error" in tech_response_raw
    fund_error = isinstance(fund_response_raw, Exception) or "error" in fund_response_raw

    if tech_error and fund_error:
        raise HTTPException(status_code=500, detail="Both Technical and Fundamental Agents failed to respond.")

    # 4. Validate and process successful responses
    tech_response, fund_response = None, None
    try:
        if not tech_error:
            tech_response = TechnicalAgentResponse(**tech_response_raw)
        if not fund_error:
            fund_response = FundamentalAgentResponse(**fund_response_raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse agent responses: {e}")

    tech_detail = None
    if tech_response:
        tech_reason, _ = get_reasons(tech_response.data.action, "hold")
        tech_detail = ReportDetail(action=tech_response.data.action, score=tech_response.data.confidence_score, reason=tech_reason)

    fund_detail = None
    if fund_response:
        _, fund_reason = get_reasons("hold", fund_response.data.action)
        fund_detail = ReportDetail(action=fund_response.data.action, score=fund_response.data.confidence_score, reason=fund_reason)

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
        entry_price = tech_response.data.current_price if tech_response else 0
        technical_stop = tech_response.data.stop_loss if tech_response else None

        trade_decision = assess_trade(
            portfolio_value=portfolio_value,
            risk_per_trade=config.RISK_PERCENTAGE,
            fixed_stop_loss_pct=config.STOP_LOSS_PERCENTAGE,
            enable_technical_stop=config.ENABLE_TECHNICAL_STOP,
            max_position_pct=config.MAX_POSITION_PERCENTAGE,
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
            new_order_response = await create_order(order_body)

            if new_order_response and new_order_response.status == "pending":
                order_id = new_order_response.order_id
                report_logger.info(f"Created order {order_id} to {final_verdict} {quantity} {ticker} @ {entry_price}")
                executed_order = await execute_order(order_id)
                if executed_order and executed_order.status == "executed":
                    report_logger.info(f"Successfully executed order {executed_order.order_id}.")
                else:
                    report_logger.error(f"Failed to execute order {order_id}.")
            else:
                report_logger.error("Failed to create trade order.")
        else:
            report_logger.warning(f"Trade for {ticker} rejected by Risk Manager: {trade_decision.get('reason')}")


    # 7. Construct and log the final report
    report = OrchestratorResponse(
        report_id=str(uuid.uuid4()),
        ticker=ticker.upper(),
        timestamp=datetime.datetime.utcnow().isoformat(),
        final_verdict=final_verdict,
        status=status,
        details=ReportDetails(technical=tech_detail, fundamental=fund_detail)
    )

    report_logger.info({
        "ticker": report.ticker, "final_verdict": report.final_verdict,
        "status": report.status, "report_id": report.report_id
    })

    return report

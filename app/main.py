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
from .risk_manager import calculate_position_size
from .config import RISK_PERCENTAGE, STOP_LOSS_PERCENTAGE

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
    if final_verdict.lower() in ["buy", "strong buy", "sell", "strong sell"]:
        price = tech_response.data.current_price if tech_response and tech_response.data else 0

        if price > 0 and balance:
            quantity = 0
            if final_verdict.lower() in ["buy", "strong buy"]:
                stop_loss_price = price * (1 - STOP_LOSS_PERCENTAGE)
                quantity = calculate_position_size(balance, RISK_PERCENTAGE, price, stop_loss_price)
                report_logger.info(f"Risk assessment for BUY: Balance=${balance.cash_balance}, Risk={RISK_PERCENTAGE*100}%, Entry=${price:.2f}, SL=${stop_loss_price:.2f}. Calculated position size: {quantity} shares.")

            elif final_verdict.lower() in ["sell", "strong sell"]:
                # Check if a position exists to sell
                existing_position = next((p for p in positions if p.symbol.lower() == ticker.lower()), None)
                if existing_position:
                    quantity = existing_position.quantity
                    report_logger.info(f"Found existing position for {ticker}. Preparing to sell {quantity} shares.")
                else:
                    quantity = 0
                    report_logger.info(f"No existing position found for {ticker}. No sell order will be placed.")


            if quantity > 0:
                order_type = "BUY" if final_verdict.lower() in ["buy", "strong buy"] else "SELL"
                order_body = CreateOrderBody(symbol=ticker, order_type=order_type, quantity=quantity, price=price)
                new_order_response = await create_order(order_body)

                if new_order_response and new_order_response.status == "pending":
                    order_id = new_order_response.order_id
                    report_logger.info(f"Created order {order_id} to {order_type} {quantity} {ticker} @ {price}")
                    executed_order = await execute_order(order_id)
                    if executed_order and executed_order.status == "executed":
                        report_logger.info(f"Successfully executed order {executed_order.order_id}.")
                    else:
                        report_logger.error(f"Failed to execute order {order_id}.")
                else:
                    report_logger.error("Failed to create trade order.")
            else:
                report_logger.info(f"No trade executed for {ticker} as calculated quantity is 0.")
        else:
            report_logger.warning(f"Could not execute trade for {ticker} due to missing price or balance information.")


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

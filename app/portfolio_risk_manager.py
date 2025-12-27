from typing import List, Dict, Any
from .risk_manager import assess_trade
from .logger import report_logger
from .models import Position

def assess_portfolio_trades(
    analysis_results: List[Dict[str, Any]],
    portfolio_value: float,
    existing_positions: List[Position],
    per_request_risk_budget: float,
    max_total_exposure: float,
    risk_per_trade: float,
    fixed_stop_loss_pct: float,
    enable_technical_stop: bool,
    max_position_pct: float,
    min_position_value: float
) -> List[Dict[str, Any]]:
    """
    Assesses a portfolio of trades, applying portfolio-level constraints.
    """

    trade_decisions = []

    # --- 1. Separate into Sell and Buy Verdicts ---
    sell_verdicts = [res for res in analysis_results if res['final_verdict'] == 'sell']
    buy_verdicts = [res for res in analysis_results if res['final_verdict'] == 'buy']

    # Sort buy verdicts by a synthesized confidence score
    def get_synthesized_score(result):
        tech_score = result['details'].technical.score if result['details'].technical else 0
        fund_score = result['details'].fundamental.score if result['details'].fundamental else 0
        # This is a simple average; a weighted average could be used here
        return (tech_score + fund_score) / 2

    buy_verdicts.sort(key=get_synthesized_score, reverse=True)

    # --- 2. Process Sell Orders First ---
    for result in sell_verdicts:
        ticker = result['ticker']
        current_position = next((p for p in existing_positions if p.symbol == ticker), None)

        sell_decision = assess_trade(
            portfolio_value=portfolio_value,
            risk_per_trade=risk_per_trade,
            fixed_stop_loss_pct=fixed_stop_loss_pct,
            enable_technical_stop=enable_technical_stop,
            max_position_pct=max_position_pct,
            symbol=ticker,
            action='sell',
            entry_price=0, # Not needed for sells
            current_position_size=current_position.quantity if current_position else 0,
        )
        trade_decisions.append(sell_decision)

    # --- 3. Process Buy Orders with Budgeting ---
    remaining_budget = portfolio_value * per_request_risk_budget

    for result in buy_verdicts:
        ticker = result['ticker']
        current_position = next((p for p in existing_positions if p.symbol == ticker), None)

        # Initial assessment to get the ideal position size and risk
        initial_decision = assess_trade(
            portfolio_value=portfolio_value,
            risk_per_trade=risk_per_trade,
            fixed_stop_loss_pct=fixed_stop_loss_pct,
            enable_technical_stop=enable_technical_stop,
            max_position_pct=max_position_pct,
            symbol=ticker,
            action='buy',
            entry_price=(
                result['raw_data']['technical'].data.current_price if result['raw_data']['technical']
                else result['raw_data']['fundamental'].data.current_price if result['raw_data']['fundamental']
                else 0
            ),
            technical_stop_loss=result['raw_data']['technical'].data.indicators.get('stop_loss') if result['raw_data']['technical'] else None,
            current_position_size=current_position.quantity if current_position else 0,
        )

        if not initial_decision['approved']:
            trade_decisions.append(initial_decision)
            continue

        required_risk = initial_decision['risk_amount']

        # --- 4. Budget and Exposure Checks ---
        if required_risk > remaining_budget:
            # --- Scale Down Logic ---
            scaling_factor = remaining_budget / required_risk
            scaled_size = int(initial_decision['position_size'] * scaling_factor)
            scaled_value = scaled_size * initial_decision['entry_price']

            if scaled_value < min_position_value:
                initial_decision['approved'] = False
                initial_decision['reason'] = f"Scaled position value ({scaled_value:.2f}) is below minimum ({min_position_value})."
                trade_decisions.append(initial_decision)
                continue

            # Update decision with scaled values
            initial_decision['position_size'] = scaled_size
            initial_decision['risk_amount'] = remaining_budget # Use up the rest of the budget
            initial_decision['reason'] = f"Position scaled down to fit risk budget."

        # --- Max Total Exposure Check ---
        current_exposure = sum(p.quantity * (p.current_market_price or p.average_cost) for p in existing_positions)
        new_trade_value = initial_decision['position_size'] * initial_decision['entry_price']

        # Recalculate total exposure including approved trades so far
        approved_buys_value = sum(
            d['position_size'] * d['entry_price']
            for d in trade_decisions
            if d.get('approved') and d['action'] == 'buy'
        )

        total_potential_exposure = current_exposure + approved_buys_value + new_trade_value

        if total_potential_exposure > portfolio_value * max_total_exposure:
            initial_decision['approved'] = False
            initial_decision['reason'] = f"Trade exceeds max total portfolio exposure limit."
            trade_decisions.append(initial_decision)
            continue

        # --- 5. Approve and Update Budget ---
        trade_decisions.append(initial_decision)
        remaining_budget -= initial_decision['risk_amount'] # Use the final, potentially scaled, risk amount

    return trade_decisions

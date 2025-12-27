from typing import List, Dict, Any
from .risk_manager import assess_trade
from .logger import report_logger
from .models import Position

class PortfolioRiskManager:
    def __init__(
        self,
        portfolio_value: float,
        existing_positions: List[Position],
        per_request_risk_budget: float,
        max_total_exposure: float,
        min_position_value: float,
    ):
        self.portfolio_value = portfolio_value
        self.existing_positions = existing_positions
        self.max_total_exposure_value = self.portfolio_value * max_total_exposure
        self.min_position_value = min_position_value

        self.remaining_budget = self.portfolio_value * per_request_risk_budget
        self.current_exposure = sum(
            p.quantity * (p.current_market_price or p.average_cost)
            for p in self.existing_positions
        )
        self.approved_buys_value = 0.0

    def evaluate_sell(self, sell_decision: Dict[str, Any]):
        """Updates portfolio exposure based on an approved sell decision."""
        if not (sell_decision.get("approved") and sell_decision.get("action") == "sell"):
            return

        position_to_sell = next(
            (p for p in self.existing_positions if p.symbol == sell_decision["symbol"]),
            None,
        )
        if position_to_sell:
            sell_value = sell_decision["position_size"] * (
                position_to_sell.current_market_price or position_to_sell.average_cost
            )
            self.current_exposure -= sell_value

    def evaluate_buy(self, buy_decision: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates a buy decision against the portfolio's budget and exposure limits."""
        if not buy_decision.get("approved"):
            return buy_decision

        decision = buy_decision.copy()
        required_risk = decision["risk_amount"]

        # --- 1. Budget Check and Scaling ---
        if required_risk > self.remaining_budget:
            scaling_factor = self.remaining_budget / required_risk
            scaled_size = int(decision["position_size"] * scaling_factor)
            scaled_value = scaled_size * decision["entry_price"]

            if scaled_value < self.min_position_value:
                decision["approved"] = False
                decision["reason"] = f"Scaled position value ({scaled_value:.2f}) is below minimum ({self.min_position_value})."
                return decision

            # Update decision with scaled values
            decision["position_size"] = scaled_size
            decision["risk_amount"] = self.remaining_budget
            decision["reason"] = f"Position scaled down to fit risk budget."

        # --- 2. Max Total Exposure Check ---
        new_trade_value = decision["position_size"] * decision["entry_price"]
        total_potential_exposure = (
            self.current_exposure + self.approved_buys_value + new_trade_value
        )

        if total_potential_exposure > self.max_total_exposure_value:
            decision["approved"] = False
            decision["reason"] = "Trade exceeds max total portfolio exposure limit."
            return decision

        # --- 3. Approve and Update State ---
        self.approved_buys_value += new_trade_value
        self.remaining_budget -= decision["risk_amount"]
        return decision


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
    min_position_value: float,
) -> List[Dict[str, Any]]:
    """
    Assesses a portfolio of trades using the PortfolioRiskManager class.
    """
    manager = PortfolioRiskManager(
        portfolio_value=portfolio_value,
        existing_positions=existing_positions,
        per_request_risk_budget=per_request_risk_budget,
        max_total_exposure=max_total_exposure,
        min_position_value=min_position_value,
    )

    final_decisions = []

    # --- 1. Separate and Sort Verdicts ---
    sell_verdicts = [res for res in analysis_results if res["final_verdict"] == "sell"]
    buy_verdicts = [res for res in analysis_results if res["final_verdict"] == "buy"]

    def get_synthesized_score(result):
        tech_score = result["details"].technical.score if result["details"].technical else 0
        fund_score = (
            result["details"].fundamental.score if result["details"].fundamental else 0
        )
        return (tech_score + fund_score) / 2

    buy_verdicts.sort(key=get_synthesized_score, reverse=True)

    # --- 2. Process Sell Orders First ---
    for result in sell_verdicts:
        ticker = result["ticker"]
        current_position = next(
            (p for p in existing_positions if p.symbol == ticker), None
        )
        sell_decision = assess_trade(
            portfolio_value=portfolio_value,
            risk_per_trade=risk_per_trade,
            fixed_stop_loss_pct=fixed_stop_loss_pct,
            enable_technical_stop=enable_technical_stop,
            max_position_pct=max_position_pct,
            symbol=ticker,
            action="sell",
            entry_price=0,
            current_position_size=current_position.quantity if current_position else 0,
        )
        manager.evaluate_sell(sell_decision)
        final_decisions.append(sell_decision)

    # --- 3. Process Buy Orders ---
    for result in buy_verdicts:
        ticker = result["ticker"]
        current_position = next(
            (p for p in existing_positions if p.symbol == ticker), None
        )
        initial_buy_decision = assess_trade(
            portfolio_value=portfolio_value,
            risk_per_trade=risk_per_trade,
            fixed_stop_loss_pct=fixed_stop_loss_pct,
            enable_technical_stop=enable_technical_stop,
            max_position_pct=max_position_pct,
            symbol=ticker,
            action="buy",
            entry_price=(
                result["raw_data"]["technical"].data.current_price
                if result.get("raw_data", {}).get("technical")
                else result["raw_data"]["fundamental"].data.current_price
                if result.get("raw_data", {}).get("fundamental")
                else 0
            ),
            technical_stop_loss=result["raw_data"]["technical"]
            .data.indicators.get("stop_loss")
            if result.get("raw_data", {}).get("technical")
            else None,
            current_position_size=current_position.quantity if current_position else 0,
        )

        final_buy_decision = manager.evaluate_buy(initial_buy_decision)
        final_decisions.append(final_buy_decision)

    return final_decisions

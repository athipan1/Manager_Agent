from typing import List, Dict, Any
from decimal import Decimal
from .risk_manager import assess_trade
from .models import Position


class PortfolioRiskManager:
    def __init__(self, portfolio_value: Decimal, existing_positions: List[Position], per_request_risk_budget: Decimal, max_total_exposure: Decimal, min_position_value: Decimal):
        self.portfolio_value = portfolio_value
        self.existing_positions = existing_positions
        self.max_total_exposure_value = self.portfolio_value * max_total_exposure
        self.min_position_value = min_position_value
        self.remaining_budget = self.portfolio_value * per_request_risk_budget
        self.current_exposure = sum(Decimal(p.quantity) * (p.current_market_price or p.average_cost) for p in self.existing_positions)
        self.approved_buys_value = Decimal("0.0")

    def evaluate_sell(self, sell_decision: Dict[str, Any]):
        if not (sell_decision.get("approved") and sell_decision.get("action") in ["sell", "strong_sell"]):
            return
        position_to_sell = next((p for p in self.existing_positions if p.symbol == sell_decision["symbol"]), None)
        if position_to_sell:
            sell_value = Decimal(sell_decision["position_size"]) * (position_to_sell.current_market_price or position_to_sell.average_cost)
            self.current_exposure -= sell_value

    def evaluate_buy(self, buy_decision: Dict[str, Any]) -> Dict[str, Any]:
        if not (buy_decision.get("approved") and buy_decision.get("action") in ["buy", "strong_buy"]):
            return buy_decision
        decision = buy_decision.copy()
        required_risk = decision["risk_amount"]
        if required_risk > self.remaining_budget:
            scaling_factor = self.remaining_budget / required_risk
            scaled_size = int(decision["position_size"] * scaling_factor)
            scaled_value = Decimal(scaled_size) * decision["entry_price"]
            if scaled_value < self.min_position_value:
                decision["approved"] = False
                decision["reason"] = f"Scaled position value ({scaled_value:.2f}) is below minimum ({self.min_position_value})."
                return decision
            decision["position_size"] = scaled_size
            decision["risk_amount"] = self.remaining_budget
            decision["reason"] = "Position scaled down to fit risk budget."

        new_trade_value = Decimal(decision["position_size"]) * decision["entry_price"]
        total_potential_exposure = self.current_exposure + self.approved_buys_value + new_trade_value
        if total_potential_exposure > self.max_total_exposure_value:
            decision["approved"] = False
            decision["reason"] = "Trade exceeds max total portfolio exposure limit."
            return decision
        self.approved_buys_value += new_trade_value
        self.remaining_budget -= decision["risk_amount"]
        return decision


def _position_price(position: Position | None) -> Decimal:
    if not position:
        return Decimal("0")
    return Decimal(position.current_market_price or position.average_cost or 0)


def _raw_data_dict(result: Dict[str, Any], agent_name: str) -> Dict[str, Any]:
    raw = (result.get("raw_data") or {}).get(agent_name) or {}
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    return raw if isinstance(raw, dict) else {}


def _current_price_from_result(result: Dict[str, Any]) -> Decimal:
    tech = _raw_data_dict(result, "technical")
    fund = _raw_data_dict(result, "fundamental")
    tech_data = tech.get("data") or {}
    fund_data = fund.get("data") or {}
    return Decimal(str(tech_data.get("current_price") or fund_data.get("current_price") or 0))


def _technical_stop_from_result(result: Dict[str, Any]):
    tech = _raw_data_dict(result, "technical")
    indicators = (tech.get("data") or {}).get("indicators") or {}
    return indicators.get("stop_loss")


def assess_portfolio_trades(analysis_results: List[Dict[str, Any]], cash_balance: Decimal, existing_positions: List[Position], per_request_risk_budget: Decimal, max_total_exposure: Decimal, risk_per_trade: Decimal, fixed_stop_loss_pct: Decimal, enable_technical_stop: bool, max_position_pct: Decimal, min_position_value: Decimal) -> List[Dict[str, Any]]:
    portfolio_value = cash_balance + sum(Decimal(p.quantity) * (p.current_market_price or p.average_cost) for p in existing_positions)
    manager = PortfolioRiskManager(portfolio_value=portfolio_value, existing_positions=existing_positions, per_request_risk_budget=per_request_risk_budget, max_total_exposure=max_total_exposure, min_position_value=min_position_value)
    final_decisions = []
    sell_verdicts = [res for res in analysis_results if res["final_verdict"] in ["sell", "strong_sell"]]
    buy_verdicts = [res for res in analysis_results if res["final_verdict"] in ["buy", "strong_buy"]]

    def get_synthesized_score(result):
        tech_score = result["details"].technical.score if result["details"].technical else 0
        fund_score = result["details"].fundamental.score if result["details"].fundamental else 0
        return (tech_score + fund_score) / 2

    buy_verdicts.sort(key=get_synthesized_score, reverse=True)

    for result in sell_verdicts:
        ticker = result["ticker"]
        current_position = next((p for p in existing_positions if p.symbol == ticker), None)
        sell_decision = assess_trade(portfolio_value=portfolio_value, risk_per_trade=risk_per_trade, fixed_stop_loss_pct=fixed_stop_loss_pct, enable_technical_stop=False, max_position_pct=max_position_pct, symbol=ticker, action=result["final_verdict"], entry_price=_position_price(current_position), current_position_size=current_position.quantity if current_position else 0)
        manager.evaluate_sell(sell_decision)
        final_decisions.append(sell_decision)

    for result in buy_verdicts:
        ticker = result["ticker"]
        current_position = next((p for p in existing_positions if p.symbol == ticker), None)
        entry_price_raw = _current_price_from_result(result)
        technical_stop_loss_raw = _technical_stop_from_result(result)
        initial_buy_decision = assess_trade(portfolio_value=portfolio_value, risk_per_trade=risk_per_trade, fixed_stop_loss_pct=fixed_stop_loss_pct, enable_technical_stop=enable_technical_stop, max_position_pct=max_position_pct, symbol=ticker, action=result["final_verdict"], entry_price=entry_price_raw, technical_stop_loss=Decimal(str(technical_stop_loss_raw)) if technical_stop_loss_raw is not None else None, current_position_size=current_position.quantity if current_position else 0)
        final_buy_decision = manager.evaluate_buy(initial_buy_decision)
        final_decisions.append(final_buy_decision)

    return final_decisions

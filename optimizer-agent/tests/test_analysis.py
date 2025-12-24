import pytest
from app.analysis import run_analysis
from app.models import (
    TradeHistory,
    PortfolioMetrics,
    OptimizerRequest,
    Trade,
    AgentSignal,
    AgentWeights,
    RiskParameters,
)

@pytest.fixture
def sample_config():
    return OptimizerRequest(
        agent_weights=AgentWeights(technical=0.6, fundamental=0.4, sentiment=0.0, macro=0.0),
        risk_parameters=RiskParameters(
            risk_per_trade=0.01,
            max_position_pct=0.1,
            stop_loss_pct=0.05,
            enable_technical_stop=True,
        ),
    )

@pytest.fixture
def stable_trade_history():
    trades = [
        Trade(ticker="AAPL", final_action="buy", entry_price=150, pnl_percent=0.05, market_condition="trend",
              technical_signal=AgentSignal(action="buy", confidence=0.8),
              fundamental_signal=AgentSignal(action="buy", confidence=0.7)),
        Trade(ticker="GOOG", final_action="buy", entry_price=2800, pnl_percent=-0.02, market_condition="range",
              technical_signal=AgentSignal(action="buy", confidence=0.6),
              fundamental_signal=AgentSignal(action="hold", confidence=0.5)),
    ]
    return TradeHistory(trades=trades)

@pytest.fixture
def degrading_trade_history():
    trades = [
        Trade(ticker="TSLA", final_action="buy", entry_price=700, pnl_percent=-0.1, market_condition="volatile",
              technical_signal=AgentSignal(action="buy", confidence=0.9),
              fundamental_signal=AgentSignal(action="buy", confidence=0.8))
        for _ in range(35)
    ]
    return TradeHistory(trades=trades)

@pytest.fixture
def stable_metrics():
    return PortfolioMetrics(win_rate=0.7, average_return=0.03, max_drawdown=0.05, sharpe_ratio=1.5,
                            exposure_by_sector={"tech": 0.5}, cash_ratio=0.5)

@pytest.fixture
def degrading_metrics():
    return PortfolioMetrics(win_rate=0.4, average_return=-0.01, max_drawdown=0.15, sharpe_ratio=-0.5,
                            exposure_by_sector={"tech": 0.8}, cash_ratio=0.2)

def test_run_analysis_stable(sample_config, stable_trade_history, stable_metrics):
    result = run_analysis(stable_trade_history, stable_metrics, sample_config)
    assert result["summary"]["overall_assessment"] == "stable"
    assert result["risk_adjustments"]["risk_per_trade"] == 0.0

def test_run_analysis_degrading(sample_config, degrading_trade_history, degrading_metrics):
    result = run_analysis(degrading_trade_history, degrading_metrics, sample_config)
    assert result["summary"]["overall_assessment"] == "degrading"
    assert result["summary"]["key_issue"] == "High losses in volatile markets and potential overtrading."
    assert result["risk_adjustments"]["risk_per_trade"] < 0
    assert result["risk_adjustments"]["stop_loss_pct"] < 0

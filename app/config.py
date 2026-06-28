import os
from dotenv import load_dotenv
import json

# Load environment variables from .env file
load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


# General Configuration
DEFAULT_ACCOUNT_ID = int(os.getenv("DEFAULT_ACCOUNT_ID", 1))

# Live trading guardrails. Default is deliberately safe.
TRADING_ENABLED = _env_bool("TRADING_ENABLED", False)
TRADING_MODE = os.getenv("TRADING_MODE", "PAPER").strip().upper()
ALLOW_LIVE_TRADING = _env_bool("ALLOW_LIVE_TRADING", False)
MANAGER_EMERGENCY_HALT = _env_bool("MANAGER_EMERGENCY_HALT", False)

# Stock-first operating mode. XAUUSD / crypto / forex are explicitly out of scope
# until later phases are enabled intentionally.
ASSET_CLASS = os.getenv("ASSET_CLASS", "stock").strip().lower()
ALLOW_SHORT_SELLING = _env_bool("ALLOW_SHORT_SELLING", False)
ALLOW_CRYPTO = _env_bool("ALLOW_CRYPTO", False)
ALLOW_FOREX = _env_bool("ALLOW_FOREX", False)
ALLOW_FRACTIONAL_SHARES = _env_bool("ALLOW_FRACTIONAL_SHARES", False)
LIVE_PREFLIGHT_REQUIRED = _env_bool("LIVE_PREFLIGHT_REQUIRED", True)
MANUAL_APPROVAL_REQUIRED = _env_bool("MANUAL_APPROVAL_REQUIRED", False)
RISK_APPROVAL_TTL_MINUTES = int(os.getenv("RISK_APPROVAL_TTL_MINUTES", 10))

if TRADING_MODE not in {"PAPER", "LIVE"}:
    raise RuntimeError("TRADING_MODE must be explicitly set to PAPER or LIVE.")

if ASSET_CLASS not in {"stock", "xauusd", "crypto", "multi"}:
    raise RuntimeError("ASSET_CLASS must be one of: stock, xauusd, crypto, multi.")

if TRADING_MODE == "LIVE" and not ALLOW_LIVE_TRADING:
    raise RuntimeError(
        "LIVE trading requested but ALLOW_LIVE_TRADING is not true. "
        "Set TRADING_MODE=PAPER for paper trading or explicitly enable live trading."
    )

if TRADING_MODE == "LIVE" and ASSET_CLASS == "stock" and (ALLOW_CRYPTO or ALLOW_FOREX):
    raise RuntimeError("Stock LIVE mode forbids ALLOW_CRYPTO/ALLOW_FOREX. Enable later phases explicitly.")

# Agent URLs (use Docker Compose service names as defaults)
TECHNICAL_AGENT_URL = os.getenv("TECHNICAL_AGENT_URL", "http://technical-agent:8002")
FUNDAMENTAL_AGENT_URL = os.getenv("FUNDAMENTAL_AGENT_URL", "http://fundamental-agent:8001")
SCANNER_AGENT_URL = os.getenv("SCANNER_AGENT_URL", "http://scanner-agent:8003")
DATABASE_AGENT_URL = os.getenv("DATABASE_AGENT_URL", "http://database-agent:8004")
AUTO_LEARNING_AGENT_URL = os.getenv("AUTO_LEARNING_AGENT_URL", "http://learning-agent:8005")
EXECUTION_AGENT_URL = os.getenv("EXECUTION_AGENT_URL", "http://execution-agent:8006")
RISK_AGENT_URL = os.getenv("RISK_AGENT_URL", "http://risk-agent:8007")
RISK_AGENT_TIMEOUT = float(os.getenv("RISK_AGENT_TIMEOUT", 10))
RISK_AGENT_FAILURE_THRESHOLD = int(os.getenv("RISK_AGENT_FAILURE_THRESHOLD", 3))
RISK_AGENT_COOLDOWN_SECONDS = float(os.getenv("RISK_AGENT_COOLDOWN_SECONDS", 30))
EXECUTION_API_KEY = os.getenv("EXECUTION_API_KEY", os.getenv("EXECUTION_AGENT_API_KEY", "dev_execution_key"))
DEFAULT_MARGIN_MULTIPLIER = float(os.getenv("DEFAULT_MARGIN_MULTIPLIER", 1.0))

# Alpha / profit-management advisory layer. These services are advisory-only and
# must never call Execution_Agent directly. Manager remains the final orchestrator.
ALPHA_AGENTS_ENABLED = _env_bool("ALPHA_AGENTS_ENABLED", False)
MARKET_REGIME_AGENT_ENABLED = _env_bool("MARKET_REGIME_AGENT_ENABLED", True)
PORTFOLIO_AGENT_ENABLED = _env_bool("PORTFOLIO_AGENT_ENABLED", True)
PROFIT_AGENT_ENABLED = _env_bool("PROFIT_AGENT_ENABLED", True)
PERFORMANCE_AGENT_ENABLED = _env_bool("PERFORMANCE_AGENT_ENABLED", True)
POLICY_REVIEW_FLOW_ENABLED = _env_bool("POLICY_REVIEW_FLOW_ENABLED", True)
MARKET_REGIME_AGENT_URL = os.getenv("MARKET_REGIME_AGENT_URL", "http://market-regime-agent:8014")
PORTFOLIO_AGENT_URL = os.getenv("PORTFOLIO_AGENT_URL", "http://portfolio-agent:8012")
PROFIT_AGENT_URL = os.getenv("PROFIT_AGENT_URL", "http://profit-agent:8011")
PERFORMANCE_AGENT_URL = os.getenv("PERFORMANCE_AGENT_URL", "http://performance-agent:8013")
CURATOR_AGENT_URL = os.getenv("CURATOR_AGENT_URL", "http://curator-agent:8015")
MARKET_REGIME_AGENT_TIMEOUT = int(os.getenv("MARKET_REGIME_AGENT_TIMEOUT", 10))
PORTFOLIO_AGENT_TIMEOUT = int(os.getenv("PORTFOLIO_AGENT_TIMEOUT", 10))
PROFIT_AGENT_TIMEOUT = int(os.getenv("PROFIT_AGENT_TIMEOUT", 10))
PERFORMANCE_AGENT_TIMEOUT = int(os.getenv("PERFORMANCE_AGENT_TIMEOUT", 10))
CURATOR_AGENT_TIMEOUT = int(os.getenv("CURATOR_AGENT_TIMEOUT", 10))
PERFORMANCE_SESSION_RISK_ENABLED = _env_bool("PERFORMANCE_SESSION_RISK_ENABLED", True)
PERFORMANCE_SESSION_RISK_REQUIRED = _env_bool("PERFORMANCE_SESSION_RISK_REQUIRED", False)
PERFORMANCE_SESSION_RISK_FILL_LIMIT = int(os.getenv("PERFORMANCE_SESSION_RISK_FILL_LIMIT", 500))

# Broker reconciliation guardrails. Manager asks Execution_Agent to pull broker truth
# and push it into Database_Agent before order submission and before DB context reads.
BROKER_RECONCILE_BEFORE_EXECUTION = _env_bool("BROKER_RECONCILE_BEFORE_EXECUTION", True)
BROKER_RECONCILE_BEFORE_CONTEXT = _env_bool("BROKER_RECONCILE_BEFORE_CONTEXT", True)
BROKER_RECONCILE_PUSH_TO_DATABASE = _env_bool("BROKER_RECONCILE_PUSH_TO_DATABASE", True)
BROKER_RECONCILE_REQUIRED = _env_bool("BROKER_RECONCILE_REQUIRED", False)
BROKER_RECONCILE_CONTEXT_REQUIRED = _env_bool("BROKER_RECONCILE_CONTEXT_REQUIRED", False)


# Resilient Agent Client Parameters
AGENT_CLIENT_TIMEOUT = int(os.getenv("AGENT_CLIENT_TIMEOUT", 10))
AGENT_CLIENT_MAX_RETRIES = int(os.getenv("AGENT_CLIENT_MAX_RETRIES", 3))
AGENT_CLIENT_BACKOFF_FACTOR = float(os.getenv("AGENT_CLIENT_BACKOFF_FACTOR", 0.5))
AGENT_CLIENT_FAILURE_THRESHOLD = int(os.getenv("AGENT_CLIENT_FAILURE_THRESHOLD", 5))
AGENT_CLIENT_COOLDOWN_PERIOD = int(os.getenv("AGENT_CLIENT_COOLDOWN_PERIOD", 30))

# Risk Management Parameters
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", 0.01))  # 1% risk per trade
MIN_RISK_PER_TRADE = float(os.getenv("MIN_RISK_PER_TRADE", 0.005)) # Min risk is 0.5%
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", 0.03)) # Max risk is 3%
STOP_LOSS_PERCENTAGE = float(os.getenv("STOP_LOSS_PERCENTAGE", 0.03))  # 3% stop loss
MAX_POSITION_PERCENTAGE = float(os.getenv("MAX_POSITION_PERCENTAGE", 0.10)) # External Risk Agent enforces final cap
ENABLE_TECHNICAL_STOP = os.getenv("ENABLE_TECHNICAL_STOP", "true").lower() in ("true", "1", "t")

# Portfolio-Level Risk Parameters
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", 0.50)) # Max 50% of portfolio value in open positions
PER_REQUEST_RISK_BUDGET = float(os.getenv("PER_REQUEST_RISK_BUDGET", 0.05)) # Max 5% total risk in a single analyze-multi call
MIN_POSITION_VALUE = float(os.getenv("MIN_POSITION_VALUE", 500.0)) # Minimum value of a position to be opened ($500)

# Agent Weights for Synthesis
AGENT_WEIGHTS = {
    "technical": float(os.getenv("TECHNICAL_AGENT_WEIGHT", 0.5)),
    "fundamental": float(os.getenv("FUNDAMENTAL_AGENT_WEIGHT", 0.5))
}

# Asset-specific biases
ASSET_BIASES = json.loads(os.getenv("ASSET_BIASES", "{}"))
MIN_ASSET_BIAS = float(os.getenv("MIN_ASSET_BIAS", -1.0))
MAX_ASSET_BIAS = float(os.getenv("MAX_ASSET_BIAS", 1.0))

# Auto-Learning Parameters
LEARNING_MODE = os.getenv("LEARNING_MODE", "conservative")
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", 50))
PREFERRED_REGIME = os.getenv("PREFERRED_REGIME", "neutral")
APPLY_LEARNING_DELTAS = _env_bool("APPLY_LEARNING_DELTAS", False)

# Database Agent Client Parameters
DB_CLIENT_TIMEOUT = int(os.getenv("DB_CLIENT_TIMEOUT", 10))
DB_CLIENT_MAX_RETRIES = int(os.getenv("DB_CLIENT_MAX_RETRIES", 3))
DB_CLIENT_BACKOFF_FACTOR = float(os.getenv("DB_CLIENT_BACKOFF_FACTOR", 0.5))
DB_CLIENT_FAILURE_THRESHOLD = int(os.getenv("DB_CLIENT_FAILURE_THRESHOLD", 5))
DB_CLIENT_COOLDOWN_PERIOD = int(os.getenv("DB_CLIENT_COOLDOWN_PERIOD", 30))
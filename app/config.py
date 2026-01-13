import os
from dotenv import load_dotenv
import json

# Load environment variables from .env file
load_dotenv()

# General Configuration
DEFAULT_ACCOUNT_ID = int(os.getenv("DEFAULT_ACCOUNT_ID", 1))

# Agent URLs (use Docker Compose service names as defaults)
TECHNICAL_AGENT_URL = os.getenv("TECHNICAL_AGENT_URL", "http://technical-agent:8000")
FUNDAMENTAL_AGENT_URL = os.getenv("FUNDAMENTAL_AGENT_URL", "http://fundamental-agent:8001")
DATABASE_AGENT_URL = os.getenv("DATABASE_AGENT_URL", "http://database-agent:8003")
AUTO_LEARNING_AGENT_URL = os.getenv("AUTO_LEARNING_AGENT_URL", "http://learning-agent:8004")
EXECUTION_AGENT_URL = os.getenv("EXECUTION_AGENT_URL", "http://execution-agent:8006")
EXECUTION_API_KEY = os.getenv("EXECUTION_API_KEY", "your_secret_key")


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
MAX_POSITION_PERCENTAGE = float(os.getenv("MAX_POSITION_PERCENTAGE", 0.20)) # Max 20% of portfolio in one stock
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

# Database Agent Client Parameters
DB_CLIENT_TIMEOUT = int(os.getenv("DB_CLIENT_TIMEOUT", 10))
DB_CLIENT_MAX_RETRIES = int(os.getenv("DB_CLIENT_MAX_RETRIES", 3))
DB_CLIENT_BACKOFF_FACTOR = float(os.getenv("DB_CLIENT_BACKOFF_FACTOR", 0.5))
DB_CLIENT_FAILURE_THRESHOLD = int(os.getenv("DB_CLIENT_FAILURE_THRESHOLD", 5))
DB_CLIENT_COOLDOWN_PERIOD = int(os.getenv("DB_CLIENT_COOLDOWN_PERIOD", 30))

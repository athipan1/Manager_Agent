import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Agent URLs
TECHNICAL_AGENT_URL = os.getenv("TECHNICAL_AGENT_URL", "http://localhost:8000/analyze")
FUNDAMENTAL_AGENT_URL = os.getenv("FUNDAMENTAL_AGENT_URL", "http://localhost:8001/analyze")
DATABASE_AGENT_URL = os.getenv("DATABASE_AGENT_URL", "http://localhost:8003")
AUTO_LEARNING_AGENT_URL = os.getenv("AUTO_LEARNING_AGENT_URL", "http://localhost:8004")

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

# Auto-Learning Parameters
LEARNING_MODE = os.getenv("LEARNING_MODE", "conservative")
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", 50))

# Database Agent Client Parameters
DB_CLIENT_TIMEOUT = int(os.getenv("DB_CLIENT_TIMEOUT", 10))
DB_CLIENT_MAX_RETRIES = int(os.getenv("DB_CLIENT_MAX_RETRIES", 3))
DB_CLIENT_BACKOFF_FACTOR = float(os.getenv("DB_CLIENT_BACKOFF_FACTOR", 0.5))
DB_CLIENT_FAILURE_THRESHOLD = int(os.getenv("DB_CLIENT_FAILURE_THRESHOLD", 5))
DB_CLIENT_COOLDOWN_PERIOD = int(os.getenv("DB_CLIENT_COOLDOWN_PERIOD", 30))

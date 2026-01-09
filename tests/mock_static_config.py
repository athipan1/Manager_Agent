# tests/mock_static_config.py

"""
A mock version of the app.config module for testing purposes.
This allows us to control the 'static' configuration values during tests
without being affected by the actual environment variables.
"""

# Agent URLs
TECHNICAL_AGENT_URL = "http://mock-technical-agent/analyze"
FUNDAMENTAL_AGENT_URL = "http://mock-fundamental-agent/analyze"
DATABASE_AGENT_URL = "http://mock-database-agent"
AUTO_LEARNING_AGENT_URL = "http://mock-auto-learning-agent"

# Risk Management Parameters (as constants)
RISK_PER_TRADE = 0.01
MIN_RISK_PER_TRADE = 0.005
MAX_RISK_PER_TRADE = 0.03
STOP_LOSS_PERCENTAGE = 0.03
MAX_POSITION_PERCENTAGE = 0.20
ENABLE_TECHNICAL_STOP = True

# Agent Weights for Synthesis
AGENT_WEIGHTS = {
    "technical": 0.5,
    "fundamental": 0.5
}

# Asset-specific biases
ASSET_BIASES = {}
MIN_ASSET_BIAS = -1.0
MAX_ASSET_BIAS = 1.0

# Database Agent Client Parameters
DB_CLIENT_TIMEOUT = 5
DB_CLIENT_MAX_RETRIES = 2
DB_CLIENT_BACKOFF_FACTOR = 0.1
DB_CLIENT_FAILURE_THRESHOLD = 3
DB_CLIENT_COOLDOWN_PERIOD = 10

# Resilient Agent Client Parameters
AGENT_CLIENT_TIMEOUT = 5
AGENT_CLIENT_MAX_RETRIES = 2
AGENT_CLIENT_BACKOFF_FACTOR = 0.1
AGENT_CLIENT_FAILURE_THRESHOLD = 3
AGENT_CLIENT_COOLDOWN_PERIOD = 10

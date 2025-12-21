import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Agent URLs
TECHNICAL_AGENT_URL = os.getenv("TECHNICAL_AGENT_URL", "http://localhost:8000/analyze")
FUNDAMENTAL_AGENT_URL = os.getenv("FUNDAMENTAL_AGENT_URL", "http://localhost:8001/analyze")
DATABASE_AGENT_URL = os.getenv("DATABASE_AGENT_URL", "http://localhost:8003") # New Database Agent URL

# Risk Management
RISK_PERCENTAGE = float(os.getenv("RISK_PERCENTAGE", 0.01))  # 1% risk per trade
STOP_LOSS_PERCENTAGE = float(os.getenv("STOP_LOSS_PERCENTAGE", 0.02))  # 2% below entry price

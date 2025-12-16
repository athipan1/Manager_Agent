import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Agent URLs
TECHNICAL_AGENT_URL = os.getenv("TECHNICAL_AGENT_URL", "http://localhost:8000/analyze")
FUNDAMENTAL_AGENT_URL = os.getenv("FUNDAMENTAL_AGENT_URL", "http://localhost:8001/analyze")
DATABASE_AGENT_URL = os.getenv("DATABASE_AGENT_URL", "http://localhost:8003/analyze")

#!/bin/bash

# Kill any existing processes on the ports
for port in 8000 8001 8002 8003 8004 8005 8006; do
    fuser -k ${port}/tcp 2>/dev/null || true
done

# Set common environment variables
export DATABASE_AGENT_API_KEY="your_database_api_key"
export EXECUTION_API_KEY="your_secret_key"
export EXECUTION_AGENT_API_KEY="your_secret_key"
export TECHNICAL_AGENT_API_KEY="your_technical_api_key"
export FUNDAMENTAL_AGENT_API_KEY="your_fundamental_api_key"
export LEARNING_AGENT_API_KEY="your_learning_api_key"
export USE_SQLITE="true"
export ALPACA_API_KEY="dummy"
export ALPACA_SECRET_KEY="dummy"

# 1. Database Agent
echo "Starting Database Agent on port 8000..."
cd Database_Agent
PYTHONPATH=. uvicorn main:app --host 0.0.0.0 --port 8000 > ../database_agent.log 2>&1 &
cd ..

# 2. Fundamental Agent
echo "Starting Fundamental Agent on port 8001..."
cd Fundamental_Agent
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8001 > ../fundamental_agent.log 2>&1 &
cd ..

# 3. Technical Agent
echo "Starting Technical Agent on port 8002..."
cd Technical_Agent
PYTHONPATH=.:app uvicorn app.main:app --host 0.0.0.0 --port 8002 > ../technical_agent.log 2>&1 &
cd ..

# 4. Scanner Agent
echo "Starting Scanner Agent on port 8003..."
cd Scanner_Agent
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8003 > ../scanner_agent.log 2>&1 &
cd ..

# 5. Learning Agent
echo "Starting Learning Agent on port 8004..."
cd Learning_Agent
export DATABASE_URL="sqlite:///./learning_agent.db"
PYTHONPATH=. uvicorn learning_agent.main:app --host 0.0.0.0 --port 8004 > ../learning_agent.log 2>&1 &
cd ..

# 6. Execution Agent
echo "Starting Execution Agent on port 8005..."
cd execution-agent
export DATABASE_AGENT_URL="http://localhost:8000"
export BROKER_MODE="SIMULATOR"
PYTHONPATH=src uvicorn src.app.main:app --host 0.0.0.0 --port 8005 > ../execution_agent.log 2>&1 &
cd ..

# Wait a bit for agents to start
echo "Waiting for agents to start..."
sleep 15

# 7. Manager Agent
echo "Starting Manager Agent on port 8006..."
export TECHNICAL_AGENT_URL="http://localhost:8002"
export FUNDAMENTAL_AGENT_URL="http://localhost:8001"
export SCANNER_AGENT_URL="http://localhost:8003"
export DATABASE_AGENT_URL="http://localhost:8000"
export AUTO_LEARNING_AGENT_URL="http://localhost:8004"
export EXECUTION_AGENT_URL="http://localhost:8005"
export PYTHONPATH=.
uvicorn app.main:app --host 0.0.0.0 --port 8006 > manager_agent.log 2>&1 &

echo "All agents started."

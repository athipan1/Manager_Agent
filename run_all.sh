#!/bin/bash

# Configuration
# Use a consistent API key across all agents for simpler E2E testing
export COMMON_API_KEY="test_secret_key"

export DATABASE_AGENT_API_KEY=$COMMON_API_KEY
export FUNDAMENTAL_AGENT_API_KEY=$COMMON_API_KEY
export TECHNICAL_AGENT_API_KEY=$COMMON_API_KEY
export LEARNING_AGENT_API_KEY=$COMMON_API_KEY
export SCANNER_AGENT_API_KEY=$COMMON_API_KEY
export EXECUTION_AGENT_API_KEY=$COMMON_API_KEY
export API_KEY=$COMMON_API_KEY # For agents that use generic API_KEY env
export DB_AGENT_API_KEY=$COMMON_API_KEY

export ALPACA_API_KEY="dummy"
export ALPACA_SECRET_KEY="dummy"

# Manager (8000)
export TECHNICAL_AGENT_URL="http://localhost:8003"
export FUNDAMENTAL_AGENT_URL="http://localhost:8002"
export SCANNER_AGENT_URL="http://localhost:8006"
export DATABASE_AGENT_URL="http://localhost:8001"
export AUTO_LEARNING_AGENT_URL="http://localhost:8004"
export EXECUTION_AGENT_URL="http://localhost:8005"
export EXECUTION_API_KEY=$COMMON_API_KEY

# Database (8001)
export USE_SQLITE="True"
export DATABASE_URL="sqlite:///trading.db"

# Execution (8005)
export DB_AGENT_URL="http://localhost:8001"
export BROKER_MODE="SIMULATOR"

# Learning (8004)
export DATABASE_AGENT_URL="http://localhost:8001"

# Kill existing processes on these ports
for port in 8000 8001 8002 8003 8004 8005 8006; do
    kill $(lsof -t -i :$port) 2>/dev/null || true
done

echo "Starting all agents..."

# Start Database Agent (8001)
(cd Database_Agent && uvicorn main:app --port 8001 > ../database.log 2>&1) &
echo "Database Agent starting..."

# Start Fundamental Agent (8002)
(cd Fundamental_Agent && uvicorn app.main:app --port 8002 > ../fundamental.log 2>&1) &
echo "Fundamental Agent starting..."

# Start Technical Agent (8003)
(cd Technical_Agent && uvicorn app.main:app --port 8003 > ../technical.log 2>&1) &
echo "Technical Agent starting..."

# Start Learning Agent (8004)
(cd Learning_Agent && uvicorn learning_agent.main:app --port 8004 > ../learning.log 2>&1) &
echo "Learning Agent starting..."

# Start Execution Agent (8005)
(cd Execution_Agent && PYTHONPATH=src uvicorn app.main:app --port 8005 > ../execution.log 2>&1) &
echo "Execution Agent starting..."

# Start Scanner Agent (8006)
(cd Scanner_Agent && uvicorn app.main:app --port 8006 > ../scanner.log 2>&1) &
echo "Scanner Agent starting..."

# Start Manager Agent (8000)
uvicorn app.main:app --port 8000 > manager.log 2>&1 &
echo "Manager Agent starting..."

echo "All agents are starting. Waiting for initialization (20s)..."
sleep 20

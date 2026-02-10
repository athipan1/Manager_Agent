#!/bin/bash

# Configuration
export DATABASE_AGENT_API_KEY="test_db_key"
export ALPACA_API_KEY="dummy"
export ALPACA_SECRET_KEY="dummy"
export FUNDAMENTAL_AGENT_API_KEY="test_fundamental_key"
export TECHNICAL_AGENT_API_KEY="test_technical_key"
export LEARNING_AGENT_API_KEY="test_learning_key"
export SCANNER_AGENT_API_KEY="test_scanner_key"
export EXECUTION_AGENT_API_KEY="test_execution_key"
export API_KEY="test_execution_key" # For Execution Agent itself

# Manager (8000)
export TECHNICAL_AGENT_URL="http://localhost:8003"
export FUNDAMENTAL_AGENT_URL="http://localhost:8002"
export SCANNER_AGENT_URL="http://localhost:8006"
export DATABASE_AGENT_URL="http://localhost:8001"
export AUTO_LEARNING_AGENT_URL="http://localhost:8004"
export EXECUTION_AGENT_URL="http://localhost:8005"
export EXECUTION_API_KEY="test_execution_key"

# Database (8001)
export USE_SQLITE="True"

# Execution (8005)
export DB_AGENT_URL="http://localhost:8001"
export DB_AGENT_API_KEY="test_db_key"
export BROKER_MODE="SIMULATOR"

# Learning (8004)
export DATABASE_AGENT_URL="http://localhost:8001"

# Kill existing processes on these ports
for port in 8000 8001 8002 8003 8004 8005 8006; do
    fuser -k $port/tcp || true
done

# Start all agents
echo "Starting Manager Agent on port 8000..."
uvicorn app.main:app --port 8000 > manager.log 2>&1 &

echo "Starting Database Agent on port 8001..."
(cd Database_Agent && uvicorn main:app --port 8001 > ../database.log 2>&1) &

echo "Starting Fundamental Agent on port 8002..."
(cd Fundamental_Agent && uvicorn app.main:app --port 8002 > ../fundamental.log 2>&1) &

echo "Starting Technical Agent on port 8003..."
(cd Technical_Agent && uvicorn app.main:app --port 8003 > ../technical.log 2>&1) &

echo "Starting Learning Agent on port 8004..."
(cd Learning_Agent && uvicorn learning_agent.main:app --port 8004 > ../learning.log 2>&1) &

echo "Starting Execution Agent on port 8005..."
(cd Execution_Agent && PYTHONPATH=src uvicorn app.main:app --port 8005 > ../execution.log 2>&1) &

echo "Starting Scanner Agent on port 8006..."
(cd Scanner_Agent && uvicorn app.main:app --port 8006 > ../scanner.log 2>&1) &

echo "All agents started. Waiting for them to initialize..."
sleep 10

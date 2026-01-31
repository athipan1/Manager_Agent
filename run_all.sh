#!/bin/bash

# Configuration for all agents
export DATABASE_AGENT_API_KEY=your_database_api_key
export TECHNICAL_AGENT_API_KEY=your_technical_api_key
export FUNDAMENTAL_AGENT_API_KEY=your_fundamental_api_key
export LEARNING_AGENT_API_KEY=your_learning_api_key
export EXECUTION_AGENT_API_KEY=your_secret_key
export EXECUTION_API_KEY=your_secret_key

# Dummy Alpaca keys to satisfy initialization
export ALPACA_API_KEY=dummy_key
export ALPACA_SECRET_KEY=dummy_secret

export USE_SQLITE=true
export DATABASE_URL=sqlite:///$(pwd)/trading.db

# URLs pointing to local ports
export DATABASE_AGENT_URL=http://localhost:8001
export DB_AGENT_URL=http://localhost:8001
export TECHNICAL_AGENT_URL=http://localhost:8002
export FUNDAMENTAL_AGENT_URL=http://localhost:8003
export SCANNER_AGENT_URL=http://localhost:8004
export AUTO_LEARNING_AGENT_URL=http://localhost:8005
export EXECUTION_AGENT_URL=http://localhost:8006

# Manager Agent specific settings
export DEFAULT_ACCOUNT_ID=1
export RISK_PER_TRADE=0.01
export STOP_LOSS_PERCENTAGE=0.03
export MAX_POSITION_PERCENTAGE=0.20
export ENABLE_TECHNICAL_STOP="true"
export MAX_TOTAL_EXPOSURE=0.50
export PER_REQUEST_RISK_BUDGET=0.05
export MIN_POSITION_VALUE=500.0
export TECHNICAL_AGENT_WEIGHT=0.5
export FUNDAMENTAL_AGENT_WEIGHT=0.5
export LEARNING_MODE=conservative
export WINDOW_SIZE=50

# PYTHONPATH
ROOT_DIR=$(pwd)
export PYTHONPATH=$ROOT_DIR

source venv/bin/activate

echo "Starting Database Agent on port 8001..."
(cd Database_Agent && python -m uvicorn main:app --host 0.0.0.0 --port 8001 > "$ROOT_DIR/database_agent.log" 2>&1) &

echo "Starting Technical Agent on port 8002..."
# Technical Agent needs app directory in PYTHONPATH to find 'service' and 'models'
(cd Technical_Agent/app && PYTHONPATH=. python -m uvicorn main:app --host 0.0.0.0 --port 8002 > "$ROOT_DIR/technical_agent.log" 2>&1) &

echo "Starting Fundamental Agent on port 8003..."
(cd Fundamental_Agent && PYTHONPATH=. python -m uvicorn app.main:app --host 0.0.0.0 --port 8003 > "$ROOT_DIR/fundamental_agent.log" 2>&1) &

echo "Starting Scanner Agent on port 8004..."
(cd Scanner_Agent && PYTHONPATH=. python -m uvicorn app.main:app --host 0.0.0.0 --port 8004 > "$ROOT_DIR/scanner_agent.log" 2>&1) &

echo "Starting Learning Agent on port 8005..."
(cd Learning_Agent && PYTHONPATH=. python -m uvicorn learning_agent.main:app --host 0.0.0.0 --port 8005 > "$ROOT_DIR/learning_agent.log" 2>&1) &

echo "Starting Execution Agent on port 8006..."
(cd execution-agent && PYTHONPATH=src python -m uvicorn app.main:app --host 0.0.0.0 --port 8006 > "$ROOT_DIR/execution_agent.log" 2>&1) &

# Give them some time to start
echo "Waiting for agents to start..."
sleep 15

echo "Starting Manager Agent on port 8000..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$ROOT_DIR/manager_agent.log" 2>&1 &

echo "All agents started."

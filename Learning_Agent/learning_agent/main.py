
from fastapi import FastAPI, Request
from .models import (
    LearningRequest, LearningResponse, MarketRegimeRequest, MarketRegimeResponse,
    BiasUpdateRequest, BiasUpdateResponse, CurrentBias, StandardAgentResponse,
    HealthData
)
from .logic import run_learning_cycle
from .market_regime import classify_market_regime
from .database import init_db, load_bias_state, save_bias_state, check_db_connection
from typing import Dict, List, Union
from collections import defaultdict
import logging

# --- Global State ---
# This will be populated from the database on startup.
BIAS_STATE: Dict[str, Dict[str, float]] = {}

app = FastAPI(
    title="Macro Learning Agent",
    description="An analytical AI responsible for strategic, long-horizon learning in an automated trading system.",
    version="1.0.0"
)

@app.on_event("startup")
def on_startup():
    """
    Initialize the database and load the initial BIAS_STATE on application startup.
    """
    global BIAS_STATE
    try:
        init_db()
        BIAS_STATE = load_bias_state()
        logging.info("Successfully initialized and loaded bias state.")
    except Exception as e:
        logging.critical(f"CRITICAL: Failed to initialize database or load state on startup: {e}")
        # If loading fails, start with a fresh defaultdict to ensure the app can still run.
        BIAS_STATE = defaultdict(lambda: {"bull_bias": 0.0, "bear_bias": 0.0, "vol_bias": 0.0})

@app.post("/learn", response_model=StandardAgentResponse[LearningResponse])
async def learn(request: LearningRequest, req: Request) -> StandardAgentResponse[LearningResponse]:
    """
    Analyzes trade history and portfolio metrics to generate incremental
    policy adjustments.
    """
    correlation_id = req.headers.get("X-Correlation-ID")
    # The learning cycle now uses the globally loaded (and persisted) BIAS_STATE
    learning_result = await run_learning_cycle(request, BIAS_STATE, correlation_id=correlation_id)
    return StandardAgentResponse(
        status="success",
        data=learning_result
    )

@app.post("/market-regime", response_model=StandardAgentResponse[MarketRegimeResponse])
async def market_regime(request: MarketRegimeRequest) -> StandardAgentResponse[MarketRegimeResponse]:
    """
    Analyzes price history to determine the current market regime.
    """
    result = classify_market_regime(request.price_history)
    return StandardAgentResponse(
        status="success",
        data=result
    )

@app.post("/learning/update-biases", response_model=StandardAgentResponse[List[BiasUpdateResponse]])
async def update_biases(request: Union[List[BiasUpdateRequest], BiasUpdateRequest]) -> StandardAgentResponse[List[BiasUpdateResponse]]:
    """
    Receives feedback from the Manager to update the agent's internal biases,
    and persists the new state to the database. Supports both single and batch updates.
    """
    updates = request if isinstance(request, list) else [request]
    responses = []

    for update in updates:
        asset_id = update.asset_id
        # Safely handle new assets by checking existence first, mimicking defaultdict behavior.
        if asset_id not in BIAS_STATE:
            BIAS_STATE[asset_id] = {"bull_bias": 0.0, "bear_bias": 0.0, "vol_bias": 0.0}
        current_asset_bias = BIAS_STATE[asset_id]

        # Apply the deltas
        current_asset_bias["bull_bias"] += update.bias_delta.bull_bias
        current_asset_bias["bear_bias"] += update.bias_delta.bear_bias
        current_asset_bias["vol_bias"] += update.bias_delta.vol_bias

        # Clamp the values to a reasonable range, e.g., [-1.0, 1.0] to prevent runaway feedback loops
        current_asset_bias["bull_bias"] = max(-1.0, min(1.0, current_asset_bias["bull_bias"]))
        current_asset_bias["bear_bias"] = max(-1.0, min(1.0, current_asset_bias["bear_bias"]))
        current_asset_bias["vol_bias"] = max(-1.0, min(1.0, current_asset_bias["vol_bias"]))

        # This modification happens in place, so BIAS_STATE is already updated here.

        response = BiasUpdateResponse(
            asset_id=asset_id,
            current_bias=CurrentBias(**current_asset_bias),
            updated=True
        )
        responses.append(response)

    # --- Persist the updated state ---
    try:
        # Pass a copy to avoid issues if the state is modified while saving
        save_bias_state(dict(BIAS_STATE))
        logging.info(f"Persisted updated bias state for {len(updates)} asset(s).")
    except Exception as e:
        logging.error(f"Failed to persist bias state after update: {e}")
        # Note: The in-memory state was updated, but persistence failed.
        # Consider adding more robust error handling or a retry mechanism here.
        # For now, we will allow the in-memory state to proceed and log the error.

    return StandardAgentResponse(
        status="success",
        data=responses
    )

@app.get("/health", response_model=StandardAgentResponse[HealthData])
def health():
    db_connected = check_db_connection()
    data = HealthData(
        status="healthy",
        database="connected" if db_connected else "disconnected"
    )
    return StandardAgentResponse(
        status="success",
        data=data
    )

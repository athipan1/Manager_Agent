
import os
import httpx
from typing import List, Dict, Optional, Union
import logging
from .models import Trade

# --- API Client ---
async def fetch_trade_history(
    account_id: Union[int, str],
    asset_id: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> List[Trade]:
    """
    Fetches trade history from the Database Agent.

    Args:
        account_id: The ID of the account to fetch history for.
        asset_id: If provided, fetches trades only for a specific asset.
        correlation_id: Optional ID for distributed tracing.

    Returns:
        A list of Trade objects. Returns an empty list if the fetch fails.
    """
    # Load configuration at runtime for better testability and CI compatibility
    db_agent_base_url = os.getenv("DB_AGENT_URL")
    db_agent_api_key = os.getenv("DB_AGENT_API_KEY")

    if not db_agent_base_url:
        logging.error("DB_AGENT_URL environment variable is not set. Cannot fetch trade history.")
        return []

    endpoint = f"{db_agent_base_url}/accounts/{account_id}/trade_history"
    params = {}
    if asset_id:
        params["asset_id"] = asset_id

    headers = {
        "X-API-KEY": db_agent_api_key or "",
        "X-Correlation-ID": correlation_id or "not-provided"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(endpoint, params=params, headers=headers, timeout=10.0)
            response.raise_for_status()  # Raise an exception for 4xx or 5xx status codes

            response_json = response.json()

            # The Database Agent now returns a StandardAgentResponse
            if isinstance(response_json, dict) and "data" in response_json:
                trade_data = response_json["data"]
            else:
                trade_data = response_json

            # Ensure trade_data is a list
            if not isinstance(trade_data, list):
                logging.error(f"Expected a list of trades from Database Agent, but got: {type(trade_data)}")
                return []

            # Parse the raw dictionary data into Pydantic Trade models, with field mapping if needed
            trades = []
            for data in trade_data:
                # Field mapping: convert 'symbol' to 'asset_id' if present
                if "symbol" in data and "asset_id" not in data:
                    data["asset_id"] = data.pop("symbol")
                trades.append(Trade(**data))

            logging.info(f"Successfully fetched {len(trades)} trades for asset '{asset_id}' from the Database Agent.")
            return trades

    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP error occurred while fetching trades for asset '{asset_id}': {e.response.status_code} - {e.response.text}")
        return []
    except httpx.RequestError as e:
        logging.error(f"An error occurred while requesting trades for asset '{asset_id}' from the Database Agent: {e}")
        return []
    except Exception as e:
        # Catch any other unexpected errors, including JSON parsing errors
        logging.error(f"An unexpected error occurred while fetching trade history for asset '{asset_id}': {e}")
        return []

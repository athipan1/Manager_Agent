from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from app.config import settings
import yfinance as yf
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def get_market_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetches current market data for a given stock symbol using a combination
    of Alpaca for the latest price and yfinance for valuation metrics.

    Args:
        symbol (str): The stock symbol (e.g., "AAPL").

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing key market data,
                                     or None if the data cannot be fetched.
    """
    market_data = {}

    # --- 1. Fetch latest price from Alpaca ---
    try:
        client = StockHistoricalDataClient(
            api_key=settings.APCA_API_KEY_ID,
            secret_key=settings.APCA_API_SECRET_KEY
        )
        request_params = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        latest_quote = client.get_stock_latest_quote(request_params)

        if latest_quote and symbol in latest_quote:
            # Using ask price as the current price
            market_data["currentPrice"] = latest_quote[symbol].ask_price
        else:
            logger.warning(f"Could not fetch price for {symbol} from Alpaca.")

    except Exception as e:
        logger.error(f"Error fetching market data for {symbol} from Alpaca: {e}")

    # --- 2. Fetch valuation metrics from yfinance ---
    try:
        stock = yf.Ticker(symbol)
        info = stock.info

        # If Alpaca failed, fall back to yfinance for price
        if "currentPrice" not in market_data:
            market_data["currentPrice"] = info.get("currentPrice")

        # Extract other metrics
        valuation_keys = ["marketCap", "industry", "sector", "pegRatio", "trailingPE", "forwardPE", "priceToBook"]
        for key in valuation_keys:
            market_data[key] = info.get(key)

    except Exception as e:
        logger.error(f"Error fetching market data for {symbol} from yfinance: {e}")

    # --- 3. Validate results ---
    # We need at least a price and the core valuation metrics to proceed.
    required_keys = ["currentPrice", "trailingPE", "pegRatio", "priceToBook"]
    if not all(key in market_data and market_data[key] is not None for key in required_keys):
        logger.warning(f"Missing essential market data for {symbol}. Cannot proceed with analysis.")
        return None

    return market_data

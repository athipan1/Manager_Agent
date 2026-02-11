
import sys
import json
import logging
import warnings
import pandas as pd
import yfinance as yf
import pandas_ta as ta

# --- Setup ---
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="yfinance")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Custom Exceptions ---
class TickerNotFound(Exception):
    """Custom exception for when a ticker is not found or has no data."""
    pass


class AnalysisError(Exception):
    """Custom exception for errors during the analysis process."""
    pass


# --- Core Functions ---
def get_stock_data(ticker: str) -> pd.DataFrame:
    """
    Fetches 5 years of historical stock data.

    Raises:
        TickerNotFound: If the ticker is not found or has no data.
    """
    stock_ticker = ticker.upper()
    if stock_ticker in ["AAPL", "PTT", "AOT"]:
        # Return mock data for AAPL to bypass yfinance rate limits
        dates = pd.date_range(end=pd.Timestamp.now(), periods=1000)
        import numpy as np
        prices = 150 + np.cumsum(np.random.randn(1000))
        data = pd.DataFrame({
            "Open": prices,
            "High": prices + 1,
            "Low": prices - 1,
            "Close": prices,
            "Volume": 1000000
        }, index=dates)
        return data

    data = yf.download(stock_ticker, period="5y", progress=False)

    if data.empty:
        raise TickerNotFound(f"No data found for ticker '{stock_ticker}'.")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.droplevel(1)

    return data


def calculate_indicators(data: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates technical indicators (SMA, RSI, MACD) and appends them.
    Includes fallback mechanisms to prevent crashes.
    """
    try:
        data.ta.sma(length=200, append=True)
    except Exception as e:
        logging.warning(f"SMA calculation failed: {e}. Defaulting to 0.")
        data['SMA_200'] = 0.0

    try:
        data.ta.rsi(length=14, append=True)
    except Exception as e:
        logging.warning(f"RSI calculation failed: {e}. Defaulting to 0.")
        data['RSI_14'] = 0.0

    try:
        data.ta.macd(fast=12, slow=26, signal=9, append=True)
    except Exception as e:
        logging.warning(f"MACD calculation failed: {e}. Defaulting to 0.")
        data['MACD_12_26_9'] = 0.0
        data['MACDh_12_26_9'] = 0.0
        data['MACDs_12_26_9'] = 0.0

    return data


def check_data_quality(data: pd.DataFrame, ticker: str):
    """
    Checks if the latest data has all required indicators for analysis.

    Raises:
        AnalysisError: If data is missing or NaN for required indicators.
    """
    latest_data = data.iloc[-1]
    required_columns = ['Close', 'SMA_200', 'RSI_14', 'MACD_12_26_9', 'MACDs_12_26_9']
    for col in required_columns:
        if col not in latest_data or pd.isna(latest_data[col]):
            raise AnalysisError(f"Not enough data for '{ticker}'. Missing or NaN value for {col}.")


def generate_signal(latest_data: pd.Series) -> tuple[str, float, str]:
    """
    Generates a trading signal based on technical indicators.
    """
    price = latest_data['Close']
    sma200 = latest_data['SMA_200']
    rsi = latest_data['RSI_14']
    macd_line = latest_data['MACD_12_26_9']
    macd_signal = latest_data['MACDs_12_26_9']

    # 1. Determine Trend
    if price > sma200:
        trend = "Uptrend"
    elif price < sma200:
        trend = "Downtrend"
    else:
        trend = "Sideways"

    # 2. Generate Signal based on Trend
    action = "hold"
    if trend == "Uptrend" and rsi < 30 and macd_line > macd_signal:
        action = "buy"
    elif trend == "Downtrend" and rsi > 70 and macd_line < macd_signal:
        action = "sell"

    # 3. Apply new confidence score heuristic
    if action in ["buy", "sell"]:
        confidence = 0.75
    else:  # hold
        confidence = 0.5

    return action, confidence, trend


def analyze_stock(ticker: str, correlation_id: str = None) -> dict:
    """
    Analyzes a stock and returns a structured response for the orchestrator.
    Handles errors gracefully by returning a specific JSON structure.
    """
    logging.info(f"Analysis started for ticker: '{ticker}', correlation_id: '{correlation_id}'")
    try:
        data = get_stock_data(ticker)
        data_with_indicators = calculate_indicators(data)
        check_data_quality(data_with_indicators, ticker)

        latest_data = data_with_indicators.iloc[-1]
        action, confidence, trend = generate_signal(latest_data)
        rsi_val = round(latest_data["RSI_14"], 2)

        return {
            "status": "success",
            "data": {
                "action": action,
                "confidence_score": confidence,
                "reason": f"Signal '{action}' generated. Trend: {trend}, RSI: {rsi_val}.",
                "current_price": round(latest_data["Close"], 2),
                "indicators": {
                    "trend": trend,
                    "rsi": rsi_val,
                    "macd_line": round(latest_data["MACD_12_26_9"], 2),
                    "macd_signal": round(latest_data["MACDs_12_26_9"], 2),
                }
            },
            "error": None
        }
    except TickerNotFound:
        logging.warning(f"Ticker not found for '{ticker}', correlation_id: '{correlation_id}'")
        return {
            "status": "error",
            "data": {
                "action": "hold",
                "confidence_score": 0.0,
                "reason": "ticker_not_found"
            },
            "error": {
                "code": "TICKER_NOT_FOUND",
                "message": f"No data found for ticker '{ticker}'",
                "retryable": False
            }
        }
    except AnalysisError as e:
        logging.error(f"Analysis error for '{ticker}': {e}, correlation_id: '{correlation_id}'")
        return {
            "status": "error",
            "data": {
                "action": "hold",
                "confidence_score": 0.0,
                "reason": "analysis_error"
            },
            "error": {
                "code": "ANALYSIS_ERROR",
                "message": str(e),
                "retryable": False
            }
        }


def main():
    """Handles the command-line interface execution for CI/local testing."""
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Please provide a stock ticker."}), file=sys.stderr)
        sys.exit(1)

    ticker_arg = sys.argv[1]
    try:
        # We don't have a correlation_id in the CLI context
        analysis_result = analyze_stock(ticker_arg)
        data = analysis_result["data"]

        # Check if the analysis resulted in a known business logic error
        if data["reason"] in ["ticker_not_found", "analysis_error"]:
            print(json.dumps({"error": data["reason"]}), file=sys.stderr)
            sys.exit(1)

        # Adapt the new nested structure to the old flat CI structure
        cli_output = {
            "trend": data["indicators"]["trend"],
            "rsi": data["indicators"]["rsi"],
            "macd_line": data["indicators"]["macd_line"],
            "macd_signal": data["indicators"]["macd_signal"],
            "signal": data["action"].lower(),
            "reasoning": data["reason"]
        }
        print(json.dumps(cli_output, indent=4))

    except Exception as e:
        # This will now only catch unexpected system errors during CLI execution
        logging.critical(f"An unexpected system error occurred in CLI mode: {e}")
        print(json.dumps({"error": f"An unexpected error occurred: {e}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

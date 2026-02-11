import yfinance as yf
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def get_financials(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetches financial statements for a given stock symbol using yfinance.

    Args:
        symbol (str): The stock symbol (e.g., "AAPL").

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing the income statement,
                                     balance sheet, and cash flow statement,
                                     or None if the data cannot be fetched.
    """
    try:
        stock = yf.Ticker(symbol)

        # Fetching quarterly data as it's often more up-to-date
        income_statement = stock.quarterly_income_stmt
        balance_sheet = stock.quarterly_balance_sheet
        cash_flow = stock.quarterly_cashflow

        if income_statement.empty or balance_sheet.empty or cash_flow.empty:
            # If any of the essential financials are missing, we can't proceed.
            return None

        return {
            "income_statement": income_statement,
            "balance_sheet": balance_sheet,
            "cash_flow": cash_flow,
            "info": stock.info # Also fetch general info which contains useful metrics
        }
    except Exception as e:
        logger.error(f"Error fetching financial data for {symbol}: {e}")
        return None

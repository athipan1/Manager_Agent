import yfinance as yf
from .exceptions import TickerNotFound, InsufficientData
from . import cache_handler


def get_financial_data(ticker: str) -> dict:
    """
    Fetches key financial data for a given stock ticker, returning raw numbers.
    It uses a cache to avoid redundant API calls.

    Args:
        ticker: The stock ticker symbol (e.g., 'AAPL').

    Returns:
        A dictionary containing the financial data.

    Raises:
        TickerNotFound: If the ticker is invalid or no data is found for it.
        InsufficientData: If some data is found, but key metrics are missing.
    """
    cache_key = f"financial_data_{ticker}"
    cached_data = cache_handler.load_from_cache(cache_key)
    if cached_data:
        print(f"Cache hit for financial data: {ticker}")
        return cached_data

    print(f"Cache miss for financial data: {ticker}. Fetching from yfinance.")
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # yfinance may return minimal info for invalid or delisted tickers.
        # A common sign is a missing 'regularMarketPrice'.
        if not info or info.get('regularMarketPrice') is None:
            raise TickerNotFound(f"No data found for ticker '{ticker}'. It may be delisted or invalid.")

        # --- Data Extraction ---
        roe = info.get('returnOnEquity')
        debt_to_equity = info.get('debtToEquity')
        profit_margins = info.get('profitMargins')
        pe_ratio = info.get('trailingPE')
        dividend_yield = info.get('dividendYield')
        pb_ratio = info.get('priceToBook')
        eps = info.get('trailingEps')
        revenue_growth = info.get('revenueGrowth')
        eps_growth = info.get('earningsGrowth')
        forward_pe = info.get('forwardPE')
        peg_ratio = info.get('pegRatio')
        operating_cashflow = info.get('operatingCashflow')

        # Check if we got any valid core data at all.
        core_metrics = [
            roe, debt_to_equity, profit_margins, pe_ratio, dividend_yield,
            pb_ratio, eps, revenue_growth, eps_growth, forward_pe, peg_ratio,
            operating_cashflow
        ]
        if all(metric is None for metric in core_metrics):
            raise InsufficientData(f"Could not retrieve any key financial metrics for {ticker}.")

        data = {
            "ROE": roe,
            "Debt to Equity Ratio": debt_to_equity,
            "Profit Margins": profit_margins,
            "P/E Ratio": pe_ratio,
            "Dividend Yield": dividend_yield,
            "P/B Ratio": pb_ratio,
            "EPS": eps,
            "Revenue Growth": revenue_growth,
            "EPS Growth": eps_growth,
            "Forward P/E": forward_pe,
            "PEG Ratio": peg_ratio,
            "Operating Cash Flow": operating_cashflow,
        }

        # --- Historical Revenue Data ---
        financials = stock.financials
        if financials is not None and not financials.empty:
            if 'Total Revenue' in financials.index:
                revenue_data = financials.loc['Total Revenue']
                # Get the last 4 years of data
                last_four_years = revenue_data.iloc[:4].to_dict()
                # Convert Timestamps to strings for JSON compatibility
                data['Historical Revenue'] = {
                    k.strftime('%Y-%m-%d'): v
                    for k, v in last_four_years.items()
                }

        # --- Dividend History ---
        dividends = stock.dividends
        if dividends is not None and not dividends.empty:
            # Get the last 5 years of dividend data
            last_5_years_dividends = dividends.resample('YE').sum().tail(5).to_dict()
            data['Dividend History'] = last_5_years_dividends

        # --- Cache successful data fetch ---
        cache_handler.save_to_cache(cache_key, data)
        return data

    except (TickerNotFound, InsufficientData) as e:
        # Re-raise our custom exceptions to be handled by the caller
        print(f"Data fetching failed for {ticker}: {e}")
        raise
    except Exception as e:
        # Catch other potential errors from yfinance (e.g., network, parsing)
        # and treat it as a case of the ticker being un-analyzable.
        print(f"An unexpected yfinance error occurred for {ticker}: {e}")
        raise TickerNotFound(f"An unexpected error occurred while fetching data for {ticker}: {e}")


if __name__ == '__main__':
    # --- Example Usage ---
    test_ticker = 'AAPL'
    financials = get_financial_data(test_ticker)

    if financials:
        print(f"Financial Data for {test_ticker}:")
        for key, value in financials.items():
            # The output will now be raw numbers (or None)
            print(f"- {key}: {value} (type: {type(value).__name__})")

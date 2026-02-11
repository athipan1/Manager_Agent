import argparse
import json
from typing import Optional
from .data_fetcher import get_financial_data
from .analyzer import analyze_financials
from .rule_based_analyzer import run_rule_based_analysis
from .exceptions import TickerNotFound, InsufficientData, ModelError
from . import cache_handler


def run_analysis(ticker: str, style: str = "growth", correlation_id: Optional[str] = None):
    """
    Runs the fundamental analysis for a given stock ticker.
    It uses a cache to avoid redundant API calls for both data and final analysis.

    Args:
        ticker (str): The stock ticker symbol.
        style (str): The analysis style ('growth', 'value', 'dividend').
        correlation_id (Optional[str]): The correlation ID for tracing.

    Returns:
        dict: A dictionary containing the analysis result or an error reason.
    """
    # Use a more structured logging approach
    log_prefix = f"[{correlation_id}] " if correlation_id else ""
    print(f"{log_prefix}--- Starting fundamental analysis for {ticker} (Style: {style}) ---")

    # --- Step 1: Check Cache for Final Analysis ---
    cache_key = f"analysis_{ticker}_{style}"
    cached_analysis = cache_handler.load_from_cache(cache_key)
    if cached_analysis:
        print(f"{log_prefix}Cache hit for final analysis: {ticker} (Style: {style})")
        return cached_analysis

    print(f"{log_prefix}Cache miss for final analysis: {ticker} (Style: {style}). Running full analysis.")
    try:
        # --- Step 2: Fetch Data (with its own caching) ---
        print(f"{log_prefix}Fetching financial data for {ticker}...")
        financial_data = get_financial_data(ticker)
        print(f"{log_prefix}Data fetched successfully.")

        # --- Step 3: Analyze Data ---
        print(f"{log_prefix}Analyzing financial data for {ticker} with LLM...")
        try:
            analysis_result = analyze_financials(ticker, financial_data, style)
            print(f"{log_prefix}LLM analysis completed successfully.")
        except ModelError as e:
            print(f"{log_prefix}LLM analysis failed: {e}. Triggering rule-based fallback.")
            analysis_result = run_rule_based_analysis(ticker, financial_data, style)
            print(f"{log_prefix}Rule-based fallback analysis completed.")

        # --- Step 4: Save to Cache ---
        cache_handler.save_to_cache(cache_key, analysis_result)

        return analysis_result

    except TickerNotFound:
        print(f"{log_prefix}Analysis failed: Ticker '{ticker}' not found.")
        return {"error": "ticker_not_found"}
    except InsufficientData:
        print(f"{log_prefix}Analysis failed: Insufficient data for '{ticker}'.")
        return {"error": "data_not_enough"}
    except Exception as e:
        # Catch any other unexpected errors
        print(f"{log_prefix}An unexpected error occurred during analysis for '{ticker}': {e}")
        return {"error": "analysis_failed"}


def main():
    """
    The main function for the Fundamental Analysis Agent when run as a script.
    It takes a stock ticker, fetches its financial data, analyzes it,
    and prints the final analysis as a JSON object.
    """
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="Fundamental Financial Analysis Agent"
    )
    parser.add_argument(
        "ticker",
        type=str,
        help="The stock ticker symbol to analyze (e.g., AAPL, GOOGL)."
    )
    parser.add_argument(
        "--style",
        type=str,
        default="growth",
        choices=["growth", "value", "dividend"],
        help="The investment analysis style."
    )
    args = parser.parse_args()

    ticker = args.ticker.upper()
    analysis_result = run_analysis(ticker, args.style)

    if analysis_result:
        # --- Step 3: Display Result ---
        print("\n--- ✅ Fundamental Analysis Complete ---")
        print(json.dumps(analysis_result, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    main()

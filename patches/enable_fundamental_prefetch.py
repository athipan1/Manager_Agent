from pathlib import Path

path = Path('/app/app/main.py')
text = path.read_text(encoding='utf-8')

old_signature = 'async def _analyze_single_asset(ticker: str, correlation_id: str) -> dict:\n    tech_response, fund_response = await call_agents(ticker, correlation_id)'
new_signature = '''async def _analyze_single_asset(ticker: str, correlation_id: str, fundamental_context: dict | None = None) -> dict:
    tech_response, fund_response = await call_agents(
        ticker,
        correlation_id,
        fundamental_context=fundamental_context,
    )'''

if old_signature in text:
    text = text.replace(old_signature, new_signature)

old_call = 'analysis_results = await asyncio.gather(*[_analyze_single_asset(ticker, correlation_id) for ticker in selected_tickers])'
new_call = '''analysis_results = await asyncio.gather(*[
            _analyze_single_asset(
                ticker,
                correlation_id,
                fundamental_context=_candidate_to_dict(ticker_to_scanner_candidate.get(ticker)),
            )
            for ticker in selected_tickers
        ])'''

if old_call in text:
    text = text.replace(old_call, new_call)

path.write_text(text, encoding='utf-8')
print('Applied Fundamental_Agent v2 prefetch patch to Manager_Agent main.py')

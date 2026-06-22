from pathlib import Path

path = Path('/app/app/main.py')
text = path.read_text(encoding='utf-8')

old_signature = 'async def _analyze_single_asset(ticker: str, correlation_id: str) -> dict:'
new_signature = 'async def _analyze_single_asset(ticker: str, correlation_id: str, fundamental_context: dict | None = None) -> dict:'
if old_signature in text and 'fundamental_context: dict | None = None' not in text:
    text = text.replace(old_signature, new_signature, 1)

old_call_direct = 'tech_response, fund_response = await call_agents(ticker, correlation_id)'
new_call_direct = '''tech_response, fund_response = await call_agents(
        ticker,
        correlation_id,
        fundamental_context=fundamental_context,
    )'''
if old_call_direct in text:
    text = text.replace(old_call_direct, new_call_direct, 1)

old_call_prefetch = 'analysis_results = await asyncio.gather(*[_analyze_single_asset(ticker, correlation_id) for ticker in selected_tickers])'
new_call_prefetch = '''analysis_results = await asyncio.gather(*[
            _analyze_single_asset(
                ticker,
                correlation_id,
                fundamental_context=_candidate_to_dict(ticker_to_scanner_candidate.get(ticker)),
            )
            for ticker in selected_tickers
        ])'''
if old_call_prefetch in text:
    text = text.replace(old_call_prefetch, new_call_prefetch, 1)

path.write_text(text, encoding='utf-8')
print('Applied Fundamental_Agent v2 prefetch patch to Manager_Agent main.py')

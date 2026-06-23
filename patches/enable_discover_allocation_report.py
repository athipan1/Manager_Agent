from pathlib import Path

path = Path('/app/app/main.py')
text = path.read_text(encoding='utf-8')

import_line = 'from .stock_preflight import run_stock_live_preflight\n'
new_import = import_line + 'from .discover_report_builder import build_discover_allocation_report\n'
if 'from .discover_report_builder import build_discover_allocation_report' not in text:
    text = text.replace(import_line, new_import, 1)

old_winner_block = 'winner, execution_result, trade_decision = ranked[0], {"status": "not_attempted", "reason": "Execution disabled or score/verdict did not qualify."}, None\n        winner_analysis, winner_symbol, winner_score = winner["analysis"], winner["symbol"], winner["score_breakdown"]["final_opportunity_score"]'
new_winner_block = 'execution_result, trade_decision = {"status": "not_attempted", "reason": "Execution disabled or score/verdict did not qualify."}, None\n        allocation_report = {"allocation_plan": {}, "winner": ranked[0], "ranked_candidates": []}\n        winner = ranked[0]\n        winner_analysis, winner_symbol, winner_score = winner["analysis"], winner["symbol"], winner["score_breakdown"]["final_opportunity_score"]'
if old_winner_block in text:
    text = text.replace(old_winner_block, new_winner_block, 1)

old_portfolio_line = 'portfolio_value = balance.cash_balance if balance else 0\n            current_position = next((p for p in positions if p.symbol == winner_symbol), None)'
new_portfolio_line = '''portfolio_value = balance.cash_balance if balance else 0
            allocation_report = build_discover_allocation_report(ranked=ranked, portfolio_value=portfolio_value, min_final_score=request.min_final_score)
            winner = allocation_report["winner"]
            winner_analysis, winner_symbol, winner_score = winner["analysis"], winner["symbol"], winner["score_breakdown"]["final_opportunity_score"]
            current_position = next((p for p in positions if p.symbol == winner_symbol), None)'''
if old_portfolio_line in text:
    text = text.replace(old_portfolio_line, new_portfolio_line, 1)

old_assess_call = 'trade_decision = assess_trade(portfolio_value=Decimal(portfolio_value), risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")), fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")), enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"), max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")), symbol=winner_symbol, action=final_verdict, entry_price=Decimal(entry_price), technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None, current_position_size=current_position.quantity if current_position else 0, current_symbol_exposure=_position_exposure(current_position), current_total_exposure=_total_position_exposure(positions), open_orders_exposure=context_value, margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)), session_risk_context=session_context)'
new_assess_call = 'trade_decision = assess_trade(portfolio_value=Decimal(portfolio_value), risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")), fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")), enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"), max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")), symbol=winner_symbol, action=final_verdict, entry_price=Decimal(entry_price), technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None, current_position_size=current_position.quantity if current_position else 0, current_symbol_exposure=_position_exposure(current_position), current_total_exposure=_total_position_exposure(positions), open_orders_exposure=context_value, margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)), session_risk_context=session_context, stock_risk_context={"strategy_bucket": winner.get("strategy_bucket") or winner.get("score_breakdown", {}).get("strategy_bucket"), "current_bucket_exposure": 0.0})'
if old_assess_call in text:
    text = text.replace(old_assess_call, new_assess_call, 1)

old_data_line = 'data = {"report_id": correlation_id, "flow": "discover_analyze_trade", "scanner_metadata": scan_payload.get("metadata", {}), "scanner_count": len(candidates), "deep_analysis_count": len(valid_results), "top_10_symbols": selected_tickers, "winner": {"symbol": winner_symbol, "final_verdict": winner_analysis.get("final_verdict"), "analysis_status": winner_analysis.get("status"), "score_breakdown": winner["score_breakdown"], "scanner_candidate": winner["scanner_candidate"], "fundamental_v2": _fundamental_v2_scores(winner_analysis)}, "ranked_candidates": [{"rank": index + 1, "symbol": item["symbol"], "final_verdict": item["analysis"].get("final_verdict"), "analysis_status": item["analysis"].get("status"), "score_breakdown": item["score_breakdown"]} for index, item in enumerate(ranked)], "trade_decision": trade_decision, "risk_approval_id": trade_decision.get("risk_approval_id") if trade_decision else None, "execution": execution_result, "dry_run_report": audit}'
new_data_line = 'data = {"report_id": correlation_id, "flow": "discover_analyze_trade", "scanner_metadata": scan_payload.get("metadata", {}), "scanner_count": len(candidates), "deep_analysis_count": len(valid_results), "top_10_symbols": selected_tickers, "allocation_plan": allocation_report.get("allocation_plan"), "winner": {"symbol": winner_symbol, "strategy_bucket": winner.get("strategy_bucket") or winner.get("score_breakdown", {}).get("strategy_bucket"), "final_verdict": winner_analysis.get("final_verdict"), "analysis_status": winner_analysis.get("status"), "score_breakdown": winner["score_breakdown"], "scanner_candidate": winner["scanner_candidate"], "fundamental_v2": _fundamental_v2_scores(winner_analysis)}, "ranked_candidates": allocation_report.get("ranked_candidates") or [{"rank": index + 1, "symbol": item["symbol"], "final_verdict": item["analysis"].get("final_verdict"), "analysis_status": item["analysis"].get("status"), "score_breakdown": item["score_breakdown"]} for index, item in enumerate(ranked)], "trade_decision": trade_decision, "risk_approval_id": trade_decision.get("risk_approval_id") if trade_decision else None, "execution": execution_result, "dry_run_report": audit}'
if old_data_line in text:
    text = text.replace(old_data_line, new_data_line, 1)

path.write_text(text, encoding='utf-8')
print('Applied discover allocation report patch to Manager_Agent main.py')

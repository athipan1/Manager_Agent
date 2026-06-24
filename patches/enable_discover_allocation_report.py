from pathlib import Path

path = Path('/app/app/main.py')
text = path.read_text(encoding='utf-8')
changes = []


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old in text:
        text = text.replace(old, new, 1)
        changes.append(label)
    elif new in text:
        changes.append(f'{label}: already_applied')
    else:
        raise RuntimeError(f'Patch target not found for {label}')


import_line = 'from .stock_preflight import run_stock_live_preflight\n'
new_import = import_line + 'from .discover_report_builder import build_discover_allocation_report\n'
if 'from .discover_report_builder import build_discover_allocation_report' not in text:
    replace_once(import_line, new_import, 'discover_report_builder_import')
else:
    changes.append('discover_report_builder_import: already_applied')

old_winner_block = 'winner, execution_result, trade_decision = ranked[0], {"status": "not_attempted", "reason": "Execution disabled or score/verdict did not qualify."}, None\n        winner_analysis, winner_symbol, winner_score = winner["analysis"], winner["symbol"], winner["score_breakdown"]["final_opportunity_score"]'
new_winner_block = 'execution_result, trade_decision = {"status": "not_attempted", "reason": "Execution disabled or score/verdict did not qualify."}, None\n        allocation_report = {"allocation_plan": {}, "bucket_selection": {}, "selected_positions": [], "position_analysis_payloads": [], "winner": ranked[0], "ranked_candidates": []}\n        winner = ranked[0]\n        winner_analysis, winner_symbol, winner_score = winner["analysis"], winner["symbol"], winner["score_breakdown"]["final_opportunity_score"]'
replace_once(old_winner_block, new_winner_block, 'legacy_winner_initialization')

old_portfolio_line = 'portfolio_value = balance.cash_balance if balance else 0\n            current_position = next((p for p in positions if p.symbol == winner_symbol), None)'
new_portfolio_line = '''portfolio_value = balance.cash_balance if balance else 0
            allocation_report = build_discover_allocation_report(ranked=ranked, portfolio_value=portfolio_value, min_final_score=request.min_final_score)
            selected_positions = allocation_report.get("selected_positions") or []
            if selected_positions:
                selected_symbols = {position["symbol"] for position in selected_positions}
                winner = next((item for item in ranked if item["symbol"] in selected_symbols), allocation_report["winner"])
            else:
                winner = allocation_report["winner"]
            winner_analysis, winner_symbol, winner_score = winner["analysis"], winner["symbol"], winner["score_breakdown"]["final_opportunity_score"]
            current_position = next((p for p in positions if p.symbol == winner_symbol), None)'''
replace_once(old_portfolio_line, new_portfolio_line, 'allocation_report_creation')

old_persist_metadata = '"selected_winner": item["symbol"] == winner_symbol'
new_persist_metadata = '"selected_for_portfolio": item["symbol"] in {position["symbol"] for position in (allocation_report.get("selected_positions") or [])}'
replace_once(old_persist_metadata, new_persist_metadata, 'persist_selected_for_portfolio')

old_assess_call = 'trade_decision = assess_trade(portfolio_value=Decimal(portfolio_value), risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")), fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")), enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"), max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")), symbol=winner_symbol, action=final_verdict, entry_price=Decimal(entry_price), technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None, current_position_size=current_position.quantity if current_position else 0, current_symbol_exposure=_position_exposure(current_position), current_total_exposure=_total_position_exposure(positions), open_orders_exposure=context_value, margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)), session_risk_context=session_context)'
new_assess_call = 'trade_decision = assess_trade(portfolio_value=Decimal(portfolio_value), risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")), fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")), enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"), max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")), symbol=winner_symbol, action=final_verdict, entry_price=Decimal(entry_price), technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None, current_position_size=current_position.quantity if current_position else 0, current_symbol_exposure=_position_exposure(current_position), current_total_exposure=_total_position_exposure(positions), open_orders_exposure=context_value, margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)), session_risk_context=session_context, stock_risk_context={"strategy_bucket": winner.get("strategy_bucket") or winner.get("score_breakdown", {}).get("strategy_bucket"), "target_weight": next((position.get("target_weight") for position in (allocation_report.get("selected_positions") or []) if position.get("symbol") == winner_symbol), None), "allocation_pct": next((position.get("allocation_pct") for position in (allocation_report.get("selected_positions") or []) if position.get("symbol") == winner_symbol), None)})'
replace_once(old_assess_call, new_assess_call, 'risk_context_allocation_metadata')

old_data_line = 'data = {"report_id": correlation_id, "flow": "discover_analyze_trade", "scanner_metadata": scan_payload.get("metadata", {}), "scanner_count": len(candidates), "deep_analysis_count": len(valid_results), "top_10_symbols": selected_tickers, "winner": {"symbol": winner_symbol, "final_verdict": winner_analysis.get("final_verdict"), "analysis_status": winner_analysis.get("status"), "score_breakdown": winner["score_breakdown"], "scanner_candidate": winner["scanner_candidate"], "fundamental_v2": _fundamental_v2_scores(winner_analysis)}, "ranked_candidates": [{"rank": index + 1, "symbol": item["symbol"], "final_verdict": item["analysis"].get("final_verdict"), "analysis_status": item["analysis"].get("status"), "score_breakdown": item["score_breakdown"]} for index, item in enumerate(ranked)], "trade_decision": trade_decision, "risk_approval_id": trade_decision.get("risk_approval_id") if trade_decision else None, "execution": execution_result, "dry_run_report": audit}'
new_data_line = 'data = {"report_id": correlation_id, "flow": "discover_analyze_trade", "mode": "portfolio_allocation", "scanner_metadata": scan_payload.get("metadata", {}), "scanner_count": len(candidates), "deep_analysis_count": len(valid_results), "top_10_symbols": selected_tickers, "allocation_plan": allocation_report.get("allocation_plan"), "bucket_selection": allocation_report.get("bucket_selection"), "selected_positions": allocation_report.get("selected_positions"), "position_analysis_payloads": allocation_report.get("position_analysis_payloads"), "risk_approvals": [trade_decision] if trade_decision else [], "execution_candidates": [{"symbol": winner_symbol, "risk": trade_decision, "execution": execution_result}] if trade_decision else [], "portfolio_summary": {"policy_name": (allocation_report.get("allocation_plan") or {}).get("policy_name"), "total_positions": len(allocation_report.get("selected_positions") or []), "approved_positions": 1 if trade_decision and trade_decision.get("approved") else 0}, "ranked_candidates": allocation_report.get("ranked_candidates") or [{"rank": index + 1, "symbol": item["symbol"], "final_verdict": item["analysis"].get("final_verdict"), "analysis_status": item["analysis"].get("status"), "score_breakdown": item["score_breakdown"]} for index, item in enumerate(ranked)], "legacy": {"winner": {"symbol": winner_symbol, "final_verdict": winner_analysis.get("final_verdict"), "analysis_status": winner_analysis.get("status"), "score_breakdown": winner["score_breakdown"], "scanner_candidate": winner["scanner_candidate"], "fundamental_v2": _fundamental_v2_scores(winner_analysis)}, "trade_decision": trade_decision, "risk_approval_id": trade_decision.get("risk_approval_id") if trade_decision else None, "execution": execution_result, "dry_run_report": audit}}'
replace_once(old_data_line, new_data_line, 'portfolio_response_shape')

path.write_text(text, encoding='utf-8')
print('Applied portfolio-first discover allocation patch to Manager_Agent main.py')
print('Changes:', ', '.join(changes))

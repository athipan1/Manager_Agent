"""Cycle-scoped diagnostics. This module has no trading/execution authority."""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COUNT_NAMES = (
    'universe_count', 'prefilter_count', 'ranked_market_count',
    'scanner_candidate_count', 'research_candidate_count',
    'deep_analysis_success_count', 'deep_analysis_failure_count',
    'final_score_pass_count', 'final_score_rejected_count',
    'allocation_selected_count', 'exposure_gate_allowed_count',
    'exposure_gate_rejected_count', 'backtest_eligible_count',
    'production_candidate_count',
)

def obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def rows(value: Any) -> list:
    return value if isinstance(value, list) else []


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def symbols(value: Any) -> set[str]:
    return {str(r.get('symbol') or r.get('ticker') or '').upper()
            for r in rows(value) if isinstance(r, dict)} - {''}


def build_funnel(source: dict, backtest: dict | None = None, cycle: dict | None = None, *, source_run_id: str | None = None) -> dict:
    response = obj(source.get('response'))
    data = obj(response.get('data'))
    scanner = obj(data.get('scanner_data'))
    metadata = obj(data.get('scanner_metadata')) or obj(scanner.get('metadata'))
    broad = obj(metadata.get('discovery_funnel'))
    ranked = rows(data.get('ranked_candidates'))
    bucket = obj(data.get('bucket_selection'))
    summary = obj(bucket.get('summary'))
    exposure = obj(data.get('exposure_gate'))
    exposure_summary = obj(exposure.get('summary'))
    threshold = number(summary.get('min_final_score', obj(source.get('request')).get('min_final_score')))
    counts: dict[str, int | None] = dict.fromkeys(COUNT_NAMES)
    counts.update({
        'universe_count': metadata.get('selected_universe_count', metadata.get('requested_universe_count')),
        'prefilter_count': broad.get('prefilter_count'),
        'ranked_market_count': broad.get('ranked_market_count'),
        'scanner_candidate_count': data.get('scanner_count', len(rows(scanner.get('candidates'))) if scanner else None),
        'research_candidate_count': data.get('research_candidate_count', len(rows(data.get('research_candidates')))),
        'deep_analysis_success_count': data.get('deep_analysis_success_count', data.get('deep_analysis_count')),
        'deep_analysis_failure_count': data.get('deep_analysis_failure_count'),
        'final_score_pass_count': sum(number(obj(r.get('score_breakdown')).get('final_opportunity_score')) is not None
             and number(obj(r.get('score_breakdown')).get('final_opportunity_score')) >= threshold
             for r in ranked) if threshold is not None and ranked else (0 if counts['deep_analysis_success_count'] == 0 else None),
        'allocation_selected_count': len(rows(data.get('pre_gate_selected_positions'))) if 'pre_gate_selected_positions' in data else None,
        'exposure_gate_allowed_count': exposure_summary.get('allowed_count'),
        'exposure_gate_rejected_count': exposure_summary.get('rejected_count'),
    })
    if not ranked and counts['deep_analysis_success_count'] == 0:
        counts['final_score_pass_count'] = 0
    # A missing counter stays unknown; absence must never imply success or zero loss.
    if counts['deep_analysis_failure_count'] is None and counts['scanner_candidate_count'] is not None and counts['deep_analysis_success_count'] is not None:
        counts['deep_analysis_failure_count'] = counts['scanner_candidate_count'] - counts['deep_analysis_success_count']
    if counts['final_score_pass_count'] is not None:
        counts['final_score_rejected_count'] = len(ranked) - counts['final_score_pass_count']
    if counts['scanner_candidate_count'] == 0:
        for key in ('deep_analysis_success_count', 'deep_analysis_failure_count', 'final_score_pass_count',
                    'final_score_rejected_count', 'allocation_selected_count', 'exposure_gate_allowed_count', 'exposure_gate_rejected_count'):
            counts[key] = 0
    rejections = [dict(r) for r in rows(broad.get('rejections'))]
    score_by_symbol = {r.get('symbol'): obj(r.get('score_breakdown')).get('final_opportunity_score') for r in ranked}

    def reject(symbol, gate, code, reason, *, observed=None, limit=None, lane='production', score=None, **extra):
        rejections.append({'symbol': symbol, 'score': score if score is not None else score_by_symbol.get(symbol),
            'threshold': limit, 'gate': gate, 'reason_code': str(code), 'reason': str(reason),
            'observed': observed, 'lane': lane, **extra})

    for evaluation in rows(bucket.get('selection_evaluations')):
        rejections.extend(dict(r) for r in rows(evaluation.get('rejections')))
    if not bucket.get('selection_evaluations'):
        # Replay older cycles from recorded values only; never recompute market signals.
        for row in ranked:
            symbol = row.get('symbol')
            score = number(score_by_symbol.get(symbol))
            if score is None or threshold is None or score < threshold:
                reject(symbol, 'final_score', 'FINAL_SCORE_BELOW_THRESHOLD' if score is not None and threshold is not None else 'FINAL_SCORE_UNAVAILABLE',
                       'Final opportunity score does not satisfy the configured minimum.', observed=score, limit=threshold)
            verdict = str(row.get('final_verdict') or '').lower()
            if verdict not in {'buy', 'strong_buy'}:
                reject(symbol, 'allocation_verdict', 'BUY_VERDICT_REQUIRED',
                       f'Final verdict is {verdict or "unavailable"}; allocation requires BUY or STRONG_BUY.', observed=verdict, limit=['buy', 'strong_buy'])
            if row.get('allows_new_entry') is False:
                reject(symbol, 'allocation_classification', 'BUCKET_CLASSIFICATION_REVIEW',
                       'Bucket classification requires review: ' + '; '.join(row.get('bucket_classification_reasons') or []),
                       observed=row.get('bucket_confidence'), limit=summary.get('auto_classify_threshold'))
            if row.get('evidence_gate_passed') is False:
                reject(symbol, 'analysis_evidence', 'ANALYSIS_EVIDENCE_INSUFFICIENT',
                       'Analysis evidence did not pass the required contract.', observed=False, limit=True)
    for result in rows(data.get('analysis_outcomes')) or rows(data.get('analysis_results')):
        if result.get('error'):
            reject(result.get('symbol') or result.get('ticker'), 'deep_analysis', 'DEEP_ANALYSIS_FAILED',
                   'Technical/Fundamental analysis failed.', observed=result.get('error'), limit='valid_analysis')
    for key, gate in [('scanner_data_quality_gate', 'data_quality'), ('scanner_opportunity_gate', 'scanner_opportunity')]:
        policy = obj(metadata.get(key))
        for row in rows(policy.get('evaluations')):
            if row.get('allowed') is False:
                reject(row.get('symbol'), gate, row.get('reason_code') or 'SCANNER_GATE_REJECTED', row.get('reason') or 'Scanner gate rejected candidate.',
                       observed=row.get('coverage_ratio', row.get('opportunity_score')),
                       limit=row.get('min_coverage_ratio', policy.get('min_opportunity_score')))
    allocation = obj(data.get('allocation_plan'))
    for gate, records in [('investability', rows(obj(allocation.get('investability_gate')).get('rejected'))),
                          ('exposure', rows(exposure.get('rejected'))),
                          ('allocation_capacity', rows(obj(allocation.get('pre_risk_capacity')).get('skipped')))]:
        for row in records:
            codes = rows(row.get('rejection_codes')) or rows(row.get('reason_codes')) or [row.get('reason_code') or f'{gate.upper()}_REJECTED']
            for code in codes:
                reject(row.get('symbol'), gate, code, row.get('reason') or row.get('reasons') or 'Candidate rejected by ' + gate,
                       observed=row.get('observed'), limit=row.get('threshold'), evidence=row)
    for name, values in bucket.items():
        for row in rows(obj(values).get('overflow')):
            reject(row.get('symbol'), 'allocation_capacity', 'BUCKET_POSITION_LIMIT',
                   'Eligible candidate exceeds the configured bucket position limit.', limit=obj(values).get('limit'))
    history = obj(source.get('pre_backtest_history_gate')) or obj(data.get('pre_backtest_history_gate'))
    for row in rows(history.get('evaluations')):
        if row.get('history_eligible') is False:
            reject(row.get('symbol'), 'backtest_history', 'BACKTEST_INSUFFICIENT_HISTORY',
                   'Insufficient bars for nested research and sealed holdout.', observed=row.get('bars_observed'), limit=row.get('bars_required'), lane='research')

    bt = obj(obj(backtest).get('data'))
    bt_correlation = obj(backtest).get('correlation_id')
    same_cycle = bool(backtest) and (bt_correlation == data.get('report_id') or
        (source_run_id is not None and bt_correlation == f'backtest-nested-{source_run_id}'))
    eligible = set(bt.get('eligible_symbols') or []) if same_cycle else set()
    if bt and same_cycle:
        counts['backtest_eligible_count'] = len(eligible)
    elif counts['scanner_candidate_count'] == 0:
        counts['backtest_eligible_count'] = 0
    for item in rows(bt.get('items')) if same_cycle else []:
        symbol = item.get('symbol')
        if symbol in eligible:
            continue
        selection = obj(item.get('selection'))
        best = obj(selection.get('best_overall'))
        reasons = rows(best.get('disqualification_reasons')) or [item.get('error') or item.get('status') or 'Exact Backtest did not approve a strategy.']
        for reason in reasons:
            reason = str(reason)
            metric = reason.split(' gate failed', 1)[0].removeprefix('walk_forward_') if reason.startswith('walk_forward_') else None
            observed = obj(best.get('walk_forward')).get(metric) if metric else best.get('score')
            limit = obj(selection.get('walk_forward_criteria')).get('min_' + metric) if metric else None
            code = ('BACKTEST_WALK_FORWARD_' + metric.upper()) if metric else 'BACKTEST_NO_ELIGIBLE_STRATEGY'
            reject(symbol, 'exact_backtest', code, reason, lane='research' if symbol not in symbols(data.get('pre_backtest_selected_positions')) else 'production',
                   strategy_id=best.get('strategy_id'), observed=observed, limit=limit,
                   validation_thresholds={'selection':selection.get('selection_criteria'), 'walk_forward':selection.get('walk_forward_criteria')},
                   failed_checks={k:v for k,v in obj(best.get('gates')).items() if v is False})
    if counts['exposure_gate_allowed_count'] == 0:
        counts['production_candidate_count'] = 0
    elif counts['backtest_eligible_count'] is not None:
        counts['production_candidate_count'] = len(symbols(data.get('pre_backtest_selected_positions')) & eligible)
    cycle = obj(cycle)
    gate = obj(cycle.get('trade_gate'))
    reason = cycle.get('reason') or gate.get('reason')
    if reason:
        for symbol in score_by_symbol:
            reject(symbol, 'cycle_trade_gate', str(reason).upper(), str(reason).replace('_', ' '), limit='all_cycle_safety_checks_pass')
    no_trade = counts['production_candidate_count'] == 0 and response.get('status') == 'success'
    if cycle.get('status') in {'controlled_no_trade', 'no_trade'}:
        no_trade = True
    unique = {}
    for r in rejections:
        unique[(r.get('symbol'), r.get('gate'), r.get('reason_code'), r.get('reason'), r.get('strategy_id'))] = r
    rejections = list(unique.values())
    code_counts = dict(Counter(r['reason_code'] for r in rejections))
    return {
        'schema_version': 'selection-funnel.v1', 'portfolio_cycle_id': data.get('report_id'), 'source_run_id': source_run_id,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source_generated_at': source.get('generated_at'), 'counts': counts,
        'stage_status': {'prefilter': broad.get('prefilter_status', 'not_recorded'),
                         'ranked_market': broad.get('ranked_market_status', 'not_recorded'),
                         'exact_backtest': 'evaluated' if bt and same_cycle else 'not_evaluated'},
        'route': broad.get('route', 'discover-best-fundamentals'),
        'fundamental_ranked_count': broad.get('fundamental_ranked_count', metadata.get('analyzed_count')),
        'outcome': 'NO_TRADE' if no_trade else ('CANDIDATES_REQUIRE_RISK' if counts['production_candidate_count'] else 'INCOMPLETE'),
        'execution_outcome': cycle.get('status', 'not_observed'),
        'cycle_reason': reason, 'rejections': rejections, 'reason_counts': code_counts,
        'candidate_outcomes': [{'symbol': s, 'score': score_by_symbol[s], 'threshold': threshold,
            'rejected_at': [r['gate'] for r in rejections if r.get('symbol') == s],
            'reason_codes': [r['reason_code'] for r in rejections if r.get('symbol') == s]} for s in score_by_symbol],
        'analysis_outcomes': rows(data.get('analysis_outcomes')),
        'provider_diagnostics': {k:metadata.get(k) for k in ('universe_source_status', 'error_categories', 'fundamental_cache', 'production_enrichment')},
        'backtest': {'tested_symbols': bt.get('symbols', []), 'eligible_symbols': sorted(eligible),
                     'research_symbols': obj(data.get('research_backtest_selection')).get('symbols', []), 'same_cycle': same_cycle},
        'safety': {'diagnostic_only': True, 'thresholds_relaxed': False, 'broker_order_authorized': False},
    }


def render(funnel: dict) -> str:
    lines = ['# Selection funnel', '', f"Cycle: `{funnel['portfolio_cycle_id']}`", '', f"Outcome: **{funnel['outcome']}**", '',
             '| Metric | Count |', '|---|---:|']
    for key, value in funnel['counts'].items():
        lines.append(f'| {key} | {value if value is not None else "not observed"} |')
    lines += ['', 'The fundamental-discovery route does not execute the market prefilter or market-ranker route. Missing measurements are not inferred as zero.',
              '', 'Research Backtest symbols do not imply production allocation or broker approval.', '',
              '| Symbol | Score | Threshold | Gate | Reason code | Reason |', '|---|---:|---|---|---|---|']
    def cell(v):
        return str(v if v is not None else '-').replace('|', '/').replace('\n', ' ')
    for r in funnel['rejections']:
        lines.append('| ' + ' | '.join(cell(r.get(k)) for k in ('symbol','score','threshold','gate','reason_code','reason')) + ' |')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reports-dir', type=Path, default=Path('reports'))
    parser.add_argument('--source-run-id', default=os.getenv('GITHUB_RUN_ID'))
    args = parser.parse_args()
    def read(name):
        path = args.reports_dir / name
        return json.loads(path.read_text()) if path.exists() else {}
    funnel = build_funnel(read('hourly-pre-backtest-discovery.json'), read('hourly-backtest-result.json'), read('hourly-manager-cycle.json'), source_run_id=args.source_run_id)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    (args.reports_dir / 'hourly-selection-funnel.json').write_text(json.dumps(funnel, indent=2, ensure_ascii=False, allow_nan=False))
    (args.reports_dir / 'hourly-selection-funnel.md').write_text(render(funnel))
    print(json.dumps({'outcome':funnel['outcome'], 'counts':funnel['counts'], 'reason_counts':funnel['reason_counts']}))

if __name__ == '__main__':
    main()

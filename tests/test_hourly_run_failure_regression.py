import json
from types import SimpleNamespace

import pytest

from scripts import run_hourly_shadow_lane as shadow
from scripts.build_selection_funnel import build_funnel
from scripts.build_hourly_operator_artifact import resolve_cycle_status
from app.services.shadow_trading_service import ShadowPlanRequest, build_shadow_trade_plan


@pytest.mark.parametrize('quantity', [1.5, float('nan'), float('inf'), -1, 0, True])
def test_manager_rejects_invalid_quantity_without_rounding(quantity):
    from app.services.order_builder import order_request_from_decision, OrderBuildError
    with pytest.raises(OrderBuildError):
        order_request_from_decision({'position_size': quantity}, 1)


def test_manager_rejects_conflicting_approved_quantities():
    from app.services.order_builder import order_request_from_decision, OrderBuildError
    with pytest.raises(OrderBuildError, match='contradictory'):
        order_request_from_decision({'position_size': 10, 'final_quantity': 9}, 1)


def candidate(**context):
    return {"symbol": "DCBO", "metadata": {"data_bundle": {"opportunity_profile": {
        "status": "review", "opportunity_score": .62,
        "execution_context": {"quote_status": "fresh", "market_session": "regular",
                              "current_price": 21, "bid": 20.99, "ask": 21.01, **context},
    }}}}


@pytest.mark.parametrize("context,reason", [
    ({"quote_status": "session_unverified"}, "shadow_session_unverified"),
    ({"ask": 0}, "shadow_quote_invalid:ask"),
    ({"ask": float('nan')}, "shadow_quote_invalid:ask"),
    ({"bid": float('inf')}, "shadow_quote_invalid:bid"),
    ({"ask": 20, "bid": 21}, "shadow_quote_invalid:crossed"),
])
def test_invalid_shadow_evidence_rejected_before_database_io(context, reason):
    with pytest.raises(ValueError, match=reason):
        build_shadow_trade_plan(ShadowPlanRequest(account_id=1, correlation_id="fixture",
                                                  candidate=candidate(**context)))


def test_shadow_error_retains_upstream_response(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.json', tmp_path / 'shadow.json'
    source.write_text(json.dumps({'response': {'data': {'research_candidates': []}}}))
    result = {"execution_mode": "shadow", "broker_order_authorized": False,
              "risk_approval_allowed": False, "execution_agent_allowed": False,
              "risk_call_count": 0, "execution_call_count": 0, "broker_order_count": 0,
              "persistence_error_count": 1,
              "persistence_errors": [{"symbol": "DCBO", "reason": "HTTP 422: ask must be positive"}]}
    calls = []
    def post(url, payload):
        calls.append(url)
        return result
    monkeypatch.setattr(shadow, '_post_json', post)
    monkeypatch.setattr('sys.argv', ['shadow', '--scanner-report', str(source), '--output', str(output)])
    with pytest.raises(SystemExit) as exc:
        shadow.main()
    assert exc.value.code == 1
    report = json.loads(output.read_text())
    assert report['status'] == 'error'
    assert report['shadow'] == result
    assert report['replay'] is None
    assert len(calls) == 1


def test_no_candidates_with_shadow_failure_is_not_no_trade():
    source = {'status': 'success', 'outcome': 'NO_TRADE', 'controlled_no_trade': True,
              'response': {'status': 'success', 'data': {'scanner_count': 0}}}
    report = build_funnel(source, phase_reports={'shadow': {'status': 'error', 'error': 'HTTP 422'}})
    assert report['outcome'] == 'SYSTEM_FAILURE'
    assert report['system_failures'][0]['phase'] == 'shadow'
    assert build_funnel(source)['outcome'] == 'NO_TRADE'


def test_controlled_no_trade_reason_codes_do_not_mask_backtest_failure():
    from scripts.record_no_candidate_cycle import build_no_candidate_report
    from scripts.resolve_hourly_trade_gate import resolve_trade_gate, build_no_trade_report
    preflight = {'status':'ready', 'portfolio_cycle_id':'fixture', 'market_open':True}
    assert build_no_candidate_report(preflight)['reason_code'] == 'NO_PRODUCTION_CANDIDATE'
    backtest = {'all_succeeded':True, 'selection_complete':True, 'eligible_symbols':[]}
    gate = resolve_trade_gate(preflight, backtest)
    report = build_no_trade_report(preflight, gate, backtest)
    assert report['outcome'] == 'NO_TRADE'
    assert report['reason_code'] == 'NO_BACKTEST_ELIGIBLE_CANDIDATE'
    assert report['safety']['execution_called'] is False
    with pytest.raises(ValueError, match='all symbols succeeded'):
        resolve_trade_gate(preflight, {**backtest, 'all_succeeded':False})


def test_session_verification_failure_is_not_normal_market_closed():
    source = {'status': 'success', 'response': {'status': 'success', 'data': {
        'scanner_count': 0, 'scanner_metadata': {'scanner_opportunity_gate': {'workflow_failure_count': 1}}}}}
    assert build_funnel(source)['outcome'] == 'SYSTEM_FAILURE'


def test_successful_reconciliation_does_not_hide_upstream_failure():
    assert resolve_cycle_status({'status': 'completed'}, {'shadow': 'failure', 'final_reconciliation': 'success'}) == 'failure'


def test_finalize_preserves_shadow_failure_when_manager_was_not_run(tmp_path, monkeypatch):
    from scripts import hourly_portfolio_cycle as cycle
    args = SimpleNamespace(phase='finalize', preflight=tmp_path/'preflight.json',
                           review=tmp_path/'review.json', manager=tmp_path/'hourly-manager-cycle.json',
                           output=tmp_path/'final.json')
    args.review.write_text('{}')
    (tmp_path/'hourly-shadow-lane.json').write_text(json.dumps({'status': 'error', 'error': 'persistence rejected'}))
    monkeypatch.setattr(cycle, 'parse_args', lambda: args)
    monkeypatch.setattr(cycle, 'load_preflight', lambda path: {'portfolio_cycle_id': 'fixture'})
    monkeypatch.setattr(cycle, 'CycleClients', lambda _: object())
    def finalize(clients, **kwargs):
        report = kwargs['report']
        assert report['candidate_cycle']['execute_requested'] is False
        return {**report, 'status': 'failed_closed', 'post_execution_reconciliation': {'status': 'synced'}}
    monkeypatch.setattr(cycle, 'finalize_cycle', finalize)
    assert cycle.main() == 1
    report = json.loads(args.output.read_text())
    assert report['upstream_failure']['phase'] == 'shadow-lane'
    assert report['post_execution_reconciliation']['status'] == 'synced'

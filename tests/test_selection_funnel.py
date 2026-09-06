from copy import deepcopy
import json
from scripts.build_selection_funnel import build_funnel, COUNT_NAMES, render
from app.discover_allocation import select_candidates_by_bucket


def source(verdict='hold', selected=False):
    positions = [{'symbol':'AAPL'}] if selected else []
    return {'status':'success', 'request':{'min_final_score':0.55}, 'response':{'status':'success', 'data':{
        'report_id':'cycle-1', 'scanner_count':1, 'deep_analysis_count':1,
        'scanner_metadata':{'selected_universe_count':1000},
        'ranked_candidates':[{'symbol':'AAPL', 'final_verdict':verdict, 'allows_new_entry':True,
            'score_breakdown':{'final_opportunity_score':0.615}}],
        'pre_gate_selected_positions':positions, 'pre_backtest_selected_positions':positions,
        'exposure_gate':{'summary':{'allowed_count':len(positions), 'rejected_count':0}},
    }}}


def test_hold_above_threshold_is_verdict_blocker():
    result = build_funnel(source())
    assert set(result['counts']) == set(COUNT_NAMES)
    assert result['counts']['final_score_pass_count'] == 1
    assert result['counts']['final_score_rejected_count'] == 0
    assert result['outcome'] == 'NO_TRADE'
    assert result['reason_counts'] == {'BUY_VERDICT_REQUIRED':1}
    assert result['counts']['prefilter_count'] is None
    assert result['counts']['ranked_market_count'] is None
    assert 'BUY_VERDICT_REQUIRED' in render(result)
    json.dumps(result, allow_nan=False)


def test_research_backtest_never_creates_production_candidate():
    bt={'correlation_id':'backtest-nested-123', 'data':{'eligible_symbols':['AAPL'], 'symbols':['AAPL']}}
    result=build_funnel(source(), bt, source_run_id='123')
    assert result['counts']['backtest_eligible_count'] == 1
    assert result['counts']['production_candidate_count'] == 0


def test_backtest_blocker_is_not_scanner_blocker():
    bt={'correlation_id':'cycle-1', 'data':{'eligible_symbols':[], 'symbols':['AAPL'], 'items':[
        {'symbol':'AAPL','status':'no_eligible_strategy','selection':{'best_overall':{
            'disqualification_reasons':['walk_forward_median_profit_factor gate failed (observed=0.8)']}}}]}}
    result=build_funnel(source('buy', True),bt)
    assert result['counts']['scanner_candidate_count'] == 1
    assert result['counts']['allocation_selected_count'] == 1
    assert result['counts']['backtest_eligible_count'] == 0
    assert result['rejections'][0]['gate'] == 'exact_backtest'
    assert result['outcome'] == 'NO_TRADE'


def test_wrong_cycle_backtest_is_not_accepted():
    bt={'correlation_id':'old-cycle','data':{'eligible_symbols':['AAPL']}}
    result=build_funnel(source('buy',True),bt)
    assert result['counts']['backtest_eligible_count'] is None
    assert result['counts']['production_candidate_count'] is None
    assert result['outcome'] == 'INCOMPLETE'


def test_no_report_is_not_a_successful_no_trade():
    result=build_funnel({})
    assert result['outcome'] == 'INCOMPLETE'
    assert result['counts']['scanner_candidate_count'] is None


def test_analysis_failure_is_not_counted_as_success():
    s=source();d=s['response']['data'];d['deep_analysis_count']=0;d['deep_analysis_failure_count']=1
    d['analysis_outcomes']=[{'symbol':'AAPL','error':'timeout'}];d['ranked_candidates']=[]
    result=build_funnel(s)
    assert result['counts']['deep_analysis_failure_count']==1
    assert any(r['gate']=='deep_analysis' for r in result['rejections'])


def test_selection_diagnostics_preserve_eligibility():
    def item(verdict,score):
        return {'symbol':'KO','analysis':{'final_verdict':verdict},
            'score_breakdown':{'final_opportunity_score':score},
            'strategy_bucket_classification':{'bucket':'core_dividend','status':'classified',
                'confidence':0.9,'allows_new_entry':True,'evidence_gate_passed':True}}
    for verdict,score,expected in [('buy',0.55,True),('hold',0.615,False),('buy',0.5499,False)]:
        result=select_candidates_by_bucket([item(verdict,score)])
        evaluation=result['selection_evaluations'][0]
        assert evaluation['eligible'] is expected
        assert bool(result['summary']['total_selected']) is expected
        for rejection in evaluation['rejections']:
            assert {'symbol','score','threshold','gate','reason_code','reason'} <= rejection.keys()


def test_preselection_e2e_keeps_success_and_records_each_analysis_failure(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app import config
    from app.models import DiscoverAnalyzeTradeRequest, ReportDetails, ReportDetail
    from app.workflows import scanner_preselection_workflow as workflow

    monkeypatch.setattr(config, 'BROKER_RECONCILE_REQUIRED', True)
    async def sync(*args):
        return {'mismatch':{'summary':{'status':'synced'}},'database':{
            'account':{'cash_balance':'100000'},'positions':[],'open_orders':[]}}
    class Scanner:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): return None
        async def discover_best_fundamentals(self,**kwargs):
            return SimpleNamespace(data={'candidates':[{'symbol':s,'candidate_score':90} for s in ['AAPL','MSFT','GOOG']],
                'metadata':{'selected_universe_count':3}})
    async def analyze(symbol,*args):
        if symbol=='MSFT': raise TimeoutError('provider unavailable')
        if symbol=='GOOG': return {'ticker':symbol,'error':'All agents failed'}
        detail=ReportDetail(action='hold',score=0.6,reason='Neutral signal')
        return {'ticker':symbol,'status':'complete','final_verdict':'hold',
            'details':ReportDetails(technical=detail,fundamental=detail),'raw_data':{}}
    monkeypatch.setattr(workflow,'load_database_sync_status',sync)
    monkeypatch.setattr(workflow,'ScannerAgentClient',Scanner)
    monkeypatch.setattr(workflow,'analyze_single_asset',analyze)
    response=asyncio.run(workflow.run_scanner_preselection_flow(
        DiscoverAnalyzeTradeRequest(account_id=1,execute=False,portfolio_cycle_id='cycle-e2e')))
    d=response.model_dump(mode='json')['data']
    assert d['deep_analysis_success_count']==1
    assert d['deep_analysis_failure_count']==2
    assert d['selected_positions']==[]
    assert d['risk_approvals']==[]
    assert d['execution_candidates']==[]
    assert d['execution']['status']=='not_requested'
    result=build_funnel({'request':{'min_final_score':0.55},'response':response.model_dump(mode='json')})
    assert result['outcome']=='NO_TRADE'
    assert {r['symbol'] for r in result['rejections'] if r['gate']=='deep_analysis'}=={'MSFT','GOOG'}
    assert result['counts']['final_score_pass_count']==1

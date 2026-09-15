"""Test-only cross-repository stages. No sockets, real keys, or production writes.

Synthetic market evidence demonstrates wiring, not a profitable strategy.
Database persistence/approved promotion are in-memory fixtures; Risk, Manager
clients, order construction, Execution service and Alpaca payload are real code.
"""

BACKTEST = r'''
from datetime import datetime, timedelta, timezone
from math import sin, pi
from app.models import PriceBar
from app.multi_strategy import MultiStrategyCandidate
from app.multi_strategy_walk_forward import WalkForwardMultiStrategyRequest
from app.nested_validation_v4 import run_walk_forward_multi_strategy_backtest_v4
prices = [100 + 15*sin(i*2*pi/12) for i in range(1008)]
bars = [PriceBar(timestamp=datetime(2021,1,1,tzinfo=timezone.utc)+timedelta(days=i),
                open=p, high=p+1, low=p-1, close=p, volume=1e7)
        for i,p in enumerate(prices)]
request = WalkForwardMultiStrategyRequest(initial_equity=100000, symbols=['TEST'],
    bars={'TEST': bars}, candidates=[MultiStrategyCandidate(strategy_id='fixture-sma-v1',
    name='Synthetic integration only', strategy='sma_crossover', fast_window=2, slow_window=3)])
result = run_walk_forward_multi_strategy_backtest_v4(request)
assert result.best_eligible is not None
assert result.best_eligible.walk_forward.passed and result.nested_walk_forward.passed
# Flat synthetic prices prove rejection with the exact same default criteria.
# These generated bars have no relationship to the sealed historical holdout.
flat_request = request.model_copy(deep=True)
flat_request.bars = {'TEST':[bar.model_copy(update={'open':100., 'high':101.,
    'low':99., 'close':100.}) for bar in bars]}
flat = run_walk_forward_multi_strategy_backtest_v4(flat_request)
assert flat.best_eligible is None
assert flat.nested_walk_forward.passed is False
emit({'strategy_id': result.best_eligible.strategy_id,
      'rejected_synthetic_backtest': flat.model_dump(mode='json'),
      'candidate_oos': result.best_eligible.walk_forward.model_dump(mode='json'),
      'nested_oos': result.nested_walk_forward.model_dump(mode='json'),
      'criteria': request.walk_forward_criteria.model_dump(mode='json'),
      'source': 'synthetic_integration_fixture', 'profitability_claim': False})
'''

RISK = r'''
from fastapi.testclient import TestClient
from app.main import app
packet = payload['request']
response = TestClient(app).request(packet['method'], packet['path'],
    json=packet['body'], headers=packet['headers'])
emit({'status_code': response.status_code, 'body': response.json()})
'''

EXECUTION = r'''
import asyncio
import httpx
from fastapi.testclient import TestClient
from app.main import app, get_broker_adapter, get_execution_service
from app.config import settings
from app.db_client import InMemoryDatabaseClient
from app.models import RiskApproval
from app.adapters.alpaca import AlpacaAdapter
from app.services.execution_service import ExecutionService
settings.TRADING_MODE = 'PAPER'
settings.TRADING_ENABLED = True
settings.ALLOW_LIVE_TRADING = False
settings.BROKER_MODE = 'ALPACA'
settings.ALPACA_API_URL = 'https://paper-api.alpaca.markets'
settings.ALPACA_API_KEY_ID = 'fixture-not-a-real-key'
settings.ALPACA_SECRET_KEY = 'fixture-not-a-real-secret'
db = InMemoryDatabaseClient()
for approval in payload['approvals'].values():
    db.seed_risk_approval(RiskApproval.model_validate(approval))
orders = []
reads = []
scenario = payload.get('scenario', 'accepted')
async def broker(request):
    assert request.url.host == 'paper-api.alpaca.markets', str(request.url)
    path = request.url.path
    if request.method == 'GET':
        reads.append(path)
        if path == '/v2/clock':
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            timestamp = (now-timedelta(hours=2)).isoformat() if scenario == 'stale_session' else now.isoformat()
            if scenario == 'malformed_clock': timestamp = 'invalid-clock'
            return httpx.Response(200, json={'timestamp':timestamp, 'is_open':True,
                'next_close':(now+timedelta(hours=1)).isoformat(),
                'next_open':(now+timedelta(days=1)).isoformat()})
        if path == '/v2/account':
            return httpx.Response(200, json={'id':'fixture-account', 'status':'ACTIVE',
                'cash':'100000', 'buying_power':'100000', 'equity':'100000',
                'trading_blocked':False, 'account_blocked':False})
        if path in {'/v2/orders', '/v2/positions'}:
            return httpx.Response(200, json=[])
    if request.method == 'POST' and path == '/v2/orders':
        order = json.loads(request.content)
        assert order['symbol'] == 'TEST' and order['side'] == 'buy'
        assert order['order_class'] == 'bracket'
        assert order['stop_loss'] and order['take_profit']
        orders.append(order)
        if scenario == 'timeout':
            raise httpx.ReadTimeout('Synthetic response lost after broker acceptance', request=request)
        if scenario == 'partial_fill':
            return httpx.Response(200, json={'id':'fixture-broker-receipt',
                'status':'partially_filled', 'filled_qty':'1', 'filled_avg_price':'100'})
        return httpx.Response(200, json={'id':'fixture-broker-receipt', 'status':'accepted'})
    raise AssertionError('Unexpected broker request: ' + str(request.url))
original_async_client = httpx.AsyncClient
httpx.AsyncClient = lambda **kwargs: original_async_client(
    transport=httpx.MockTransport(broker), trust_env=False)
adapter = AlpacaAdapter()
service = ExecutionService(db, adapter)
app.dependency_overrides[get_broker_adapter] = lambda: adapter
app.dependency_overrides[get_execution_service] = lambda: service
packet = payload['request']
client = TestClient(app)
response = client.request(packet['method'], packet['path'], json=packet['body'],
    headers={**packet['headers'], 'X-API-KEY': settings.API_KEY})
assert response.status_code == (202 if packet['path'] == '/execute/batch' else 200), response.text
data = response.json()['data']
if scenario in {'stale_session', 'malformed_clock', 'timeout'}:
    assert data['approved'] is False and not data['created'] and data['failed'], data
if scenario in {'stale_session', 'malformed_clock'}:
    assert 'session_unverified' in data['failed'][0]['reason'], data
if scenario == 'partial_fill':
    assert data['created'][0]['status'] == 'partially_filled', data
if packet['path'] == '/execute/batch' and response.status_code == 202:
    expected_submissions = 0 if scenario in {'stale_session', 'malformed_clock'} else 1
    assert len(orders) == expected_submissions, response.text
    # The same persisted order/consumed approval must not submit twice.
    replay = client.post(packet['path'], json=packet['body'],
        headers={'X-API-KEY': settings.API_KEY})
    assert len(orders) == expected_submissions, replay.text
    # A new service instance models a sequential workflow/process retry against
    # the same persisted database. This does NOT model distributed concurrency.
    retry_service = ExecutionService(db, adapter)
    app.dependency_overrides[get_execution_service] = lambda: retry_service
    retry = client.post(packet['path'], json=packet['body'],
        headers={'X-API-KEY': settings.API_KEY, 'X-Correlation-ID':'workflow-retry'})
    assert len(orders) == expected_submissions, retry.text
    if scenario == 'timeout':
        assert 'BROKER_SUBMISSION_REQUIRES_RECONCILIATION' in retry.text, retry.text
    assert '/v2/clock' in reads and '/v2/account' in reads and '/v2/positions' in reads and '/v2/orders' in reads
emit({'status_code': response.status_code, 'body': response.json(),
      'scenario': scenario, 'retry_body': retry.json() if 'retry' in locals() else None,
      'mock_broker_orders': orders, 'broker_preflight_reads': reads,
      'replay_broker_order_count': len(orders)})
'''

MANAGER = r'''
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import httpx
from app import config, risk_agent_client
from app.execution_client import ExecutionAgentClient
from app.workflows.execution_workflow import execute_portfolio_batch
from app.services.promotion_execution_gate import filter_candidates_with_promotion_gate
assert payload['manager']['selected_positions'], payload['manager']
assert payload['backtest']['candidate_oos']['passed']
assert payload['backtest']['nested_oos']['passed']
candidate = payload['manager']['ranked'][0]
assert candidate['evidence_gate_passed'] is True
strategy = payload['backtest']['strategy_id']
correlation = 'hourly-paper-fixture-integration-20260909T14'
config.TRADING_MODE = 'PAPER'
config.EXECUTION_AGENT_URL = 'http://execution-fixture'
risk_agent_client.RISK_AGENT_URL = 'http://risk-fixture'
# This in-memory double emulates the trusted Database contract. The entire
# harness is fixture-only, blocks all sockets, and emits production_authorized=False.
class Database:
    def __init__(self): self.approvals = {}; self.existing_order = None
    async def get_order_by_trade_id(self, *args): return self.existing_order
    async def get_risk_approval(self, approval_id, *args): return self.approvals.get(approval_id)
    async def create_risk_approval(self, record, *args): self.approvals[record['approval_id']] = record
    async def _get(self, path, correlation_id, **kwargs):
        assert path == '/backtests/promotions/latest/exact'
        expected = kwargs['params']
        return {'status':'success', 'data': {**expected,
            'skill_id':'hourly-sma-crossover', 'strategy_id':strategy, 'symbol':'TEST',
            'promotion_id':'fixture-approved-promotion', 'run_id':'fixture-backtest-run',
            'state':'APPROVED_FOR_PAPER', 'version':4, 'evidence_version':3,
            'updated_at':datetime.now(timezone.utc).isoformat(),
            'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}}
    def validate_standard_response(self, value): return SimpleNamespace(data=value['data'])
db = Database()
rpc_evidence = []
async def dispatch(request):
    assert request.url.host in {'risk-fixture','execution-fixture'}, str(request.url)
    packet = {'service':'Risk_Agent' if request.url.host == 'risk-fixture' else 'Execution_Agent',
        'request': {'method':request.method, 'path':request.url.path,
                    'body':json.loads(request.content) if request.content else None,
                    'headers':{'X-Correlation-ID':correlation}}, 'approvals':db.approvals}
    print('DECISION_E2E_RPC=' + json.dumps(packet), flush=True)
    answer = json.loads(sys.stdin.readline())
    if 'rpc_error' in answer: raise AssertionError(answer['rpc_error'])
    rpc_evidence.append({'service':packet['service'], 'path':request.url.path, **answer})
    return httpx.Response(answer['status_code'], json=answer['body'])
original_client = httpx.AsyncClient
def fixture_client(*args, **kwargs):
    kwargs['transport'] = httpx.MockTransport(dispatch)
    return original_client(*args, **kwargs)
httpx.AsyncClient = fixture_client
async def run():
    from app.services.promotion_execution_gate import _decision
    rejected_fixture = _decision(promotion={'fixture_only':True}, lookup_error=None,
        account_id='1', symbol='TEST', skill_id='hourly-sma-crossover', strategy_id=strategy,
        timeframe='1d', max_age_hours=26, now=datetime.now(timezone.utc), auto_approve=False)
    assert rejected_fixture['allowed'] is False
    assert 'backtest_fixture_or_research_has_no_production_authority' in rejected_fixture['rejection_codes']
    gate = await filter_candidates_with_promotion_gate(db_client=db,
        selected_positions=payload['manager']['selected_positions'],
        position_analysis_payloads=[{'ticker':'TEST'}], correlation_id=correlation,
        required=True, skill_id='hourly-sma-crossover', strategy_id=strategy,
        strategy_ids=[strategy], timeframe='1d', max_age_hours=26,
        walk_forward_required=True, account_id='1', auto_approve=False)
    assert gate['summary']['allowed_count'] == 1, gate
    promotion_rejections = {}
    for stage, state in [('candidate_oos', 'VALIDATED'), ('nested_oos', 'OOS_PASSED')]:
        promotion = (await db._get('/backtests/promotions/latest/exact', correlation,
            params={'account_id':'1', 'timeframe':'1d', 'validation_profile':'nested_walk_forward_v2'}))['data']
        promotion['state'] = state
        rejected = _decision(promotion=promotion, lookup_error=None, account_id='1',
            symbol='TEST', skill_id='hourly-sma-crossover', strategy_id=strategy,
            timeframe='1d', max_age_hours=26, now=datetime.now(timezone.utc), auto_approve=False)
        assert not rejected['allowed']
        assert 'backtest_promotion_not_robustness_passed' in rejected['rejection_codes']
        assert rejected['rejection_codes'] == ['backtest_promotion_not_robustness_passed'], rejected
        promotion_rejections[stage] = rejected
    risk_payload = {'account_id':1, 'symbol':'TEST', 'side':'buy', 'entry_price':100,
        'protection_price':95, 'equity':100000, 'requested_quantity':10,
        'current_symbol_exposure':0, 'current_total_exposure':0, 'open_orders_exposure':0,
        'current_sector_exposure':0, 'owned_quantity':0, 'margin_multiplier':1,
        'trading_mode':'PAPER', 'asset_class':'stock', 'sector':'Technology',
        'strategy_bucket':candidate['strategy_bucket'], 'bucket_confidence':candidate['bucket_confidence'],
        'bucket_classification_status':candidate['bucket_classification_status'],
        'bucket_classifier_version':'manager-strategy-bucket-v2',
        'daily_realized_pnl':0, 'weekly_realized_pnl':0, 'consecutive_losses':0,
        'trades_today':0, 'symbol_trades_today':0, 'emergency_halt':False}
    risk = await risk_agent_client.evaluate_risk_async(deepcopy(risk_payload), correlation)
    assert risk['data']['approved'] is True, risk
    halted = await risk_agent_client.evaluate_risk_async({**risk_payload, 'emergency_halt':True}, correlation)
    assert halted['data']['approved'] is False, halted
    rejected_risk = await risk_agent_client.evaluate_risk_async(
        {**risk_payload, 'current_total_exposure':1000000}, correlation)
    assert rejected_risk['data']['approved'] is False, rejected_risk
    decision = {'symbol':'TEST', 'action':'buy', 'approved':True,
        'position_size':int(risk['data']['final_quantity']),
        'risk_approval_id':'fixture-approved-risk', 'risk_agent_response':risk,
        'strategy_bucket':candidate['strategy_bucket'], 'strategy_id':strategy,
        'entry_price':100, 'stop_loss':95, 'take_profit':110}
    async with ExecutionAgentClient() as client:
        result = await execute_portfolio_batch(exec_client=client, decisions=[decision],
            account_id=1, correlation_id=correlation, db_client=db)
        assert result['status'] == 'submitted' and len(result['created']) == 1, result
        assert result['created'][0]['broker_order_id'] == 'fixture-broker-receipt', result
        db.existing_order = result['created'][0]
        replay = await execute_portfolio_batch(exec_client=client, decisions=[decision],
            account_id=1, correlation_id=correlation, db_client=db)
        assert replay['status'] == 'not_attempted' and replay['duplicate_orders'], replay
    emit({'fixture_only':True, 'production_authorized':False, 'profitability_claim':False,
          'fixture_authority_rejection':rejected_fixture, 'backtest_gate':gate, 'risk':risk, 'halt_rejection':halted,
          'promotion_rejections':promotion_rejections, 'risk_rejection':rejected_risk,
          'execution':result, 'manager_replay':replay, 'rpc_evidence':rpc_evidence})
asyncio.run(run())
'''

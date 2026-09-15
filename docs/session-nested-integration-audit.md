# Session / nested-OOS / integration audit

Baseline: Manager PR #442; existing Hourly Auto Trading run #34365426015.
Verification update: 2026-09-15. Scanner #42 and Execution #89 have merged after
green existing CI; Backtest #67 is under CI/research verification. Manager publication
follows dependency verification. No new Paper run or production order is claimed.
No repository or workflow has been created. Existing Execution CI now runs its full suite.

## Session root cause

Hourly preflight recorded Alpaca Paper clock `2026-09-09T10:43:02.277956065-04:00`,
`market_open=true`, next close `2026-09-09T16:00:00-04:00`.
This historical preflight is a comparison, NOT fresh execution authority nine minutes later.

| Symbol | Snapshot UTC | Quote UTC | Quote age s | Exchange | Recorded session | Provider provenance |
|---|---|---|---:|---|---|---|
| WDC | 2026-09-09 14:52:34.504168 | 14:52:30.775217 | 3.729 | NASDAQ / NMS | premarket / false | reused yfinance `PRE` |
| JFIN | not retained | 14:51:19.164943 | 76.152 | not retained in execution context | premarket / false | full provider snapshot not retained |
| QTTB | 2026-09-09 14:52:35.777756 | 14:52:14.057773 | 21.720 | NASDAQ / NCM | premarket / false | reused yfinance `PRE` |

Snapshot UTC 14:52 corresponds to 10:52 America/New_York (UTC−04), not premarket.
The original quote classifier prioritized provider `marketState` from reused metadata
over current broker session. Fresh Alpaca quotes and stale provider session metadata
were combined in the same snapshot. WDC/QTTB cached fundamental data were about three
hours old. Separate provider timestamp/timezone was not retained: do not invent it.

The Scanner fix reads ONLY the Paper `/v2/clock`, caches it at most five seconds,
checks aware timestamps, boolean `is_open`, 30-second age, future skew and next session
boundary. Invalid/missing authority fails closed as `session_unverified` and Manager
classifies it as a data failure, not normal market closure. Freshness is measured after
provider I/O. Provider session remains separately visible; canonical execution fields
come from validated broker authority. Quote freshness, spread and other safety gates remain.
WDC/JFIN/QTTB also had wide spreads (~423/1655/1439 bps): correcting session does not admit them.

## Nested OOS diagnosis

Only BSX among the three backtested symbols in this run passed candidate OOS.
BKNG and QTTB failed candidate OOS too; they must not be described as members of a
candidate-pass/nested-fail cohort. Earlier IA evidence is from a different run and is
not same-cycle production authority.

BSX used the only compatible candidate, SMA 10/30. Six 126-bar training slices had
9, 7, 8, 5, 4, 4 trades, all below the unchanged minimum 10. This establishes a training
sample-size rejection in every fold. Historical artifacts did not serialize every
inner gate: additional rejection causes cannot be reconstructed with certainty.

| Fold | Training dates | Outer OOS dates | Train trades | Candidate OOS trades | Return | Sharpe | Sortino | Max DD |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | 2021-09-13–2022-03-15 | 2022-03-16–2022-09-14 | 9 | 7 | .003166 | .436281 | .762916 | -.006879 |
| 2 | 2022-03-16–2022-09-14 | 2022-09-15–2023-03-16 | 7 | 8 | .004727 | .606932 | .905346 | -.009894 |
| 3 | 2022-09-15–2023-03-16 | 2023-03-17–2023-09-15 | 8 | 5 | -.007786 | -1.459615 | -1.840970 | -.010624 |
| 4 | 2023-03-17–2023-09-15 | 2023-09-18–2024-03-18 | 5 | 4 | .023384 | 3.160673 | 5.825864 | -.002761 |
| 5 | 2023-09-18–2024-03-18 | 2024-03-19–2024-09-17 | 4 | 4 | .010082 | 1.532424 | 2.149527 | -.005638 |
| 6 | 2024-03-19–2024-09-17 | 2024-09-18–2025-03-20 | 4 | 8 | .005864 | .794845 | 1.155569 | -.006672 |

Returns/DD are decimals. Each candidate OOS fold applies fee 10 bps and slippage 5 bps
per side; impact is zero. Historical fees paid and monetary slippage are not separately
recorded, not zero. Nested deployment abstained in ALL six folds: zero trades, zero cash
return/DD, undefined Sharpe/Sortino. The candidate OOS returns above are NOT deployed
nested returns. Validation occurs inside the training slice, with no separate inner
validation period. The 252-bar final holdout was sealed and not opened.

Candidate median Sharpe .700889 barely exceeds .7. The strong fourth/fifth folds and
negative third fold suggest regime sensitivity, not a proven causal regime attribution.
Only one fixed parameter pair was evaluated; parameter-neighborhood stability cannot
be established. Sparse samples and post-selection candidate reporting can overstate
robustness. Nested rejection is justified; no threshold was reduced. BKNG nested
median Sharpe .22258 and profitable rate .333333 fail .7/.6; QTTB .16051 and .5 fail too.

New Backtest diagnostics preserve every training candidate, effective parameters,
actual/missing gate values, thresholds, statistical evidence, costs and rejection class
before abstention. Missing gates are contract failures; observed threshold failures are
policy rejections. The report includes training and OOS metrics for every retained fold.
No selection behavior or thresholds were changed.

### Archived IA cohort (separate run)

The retained `hourly-backtest-ia.json` evaluated `sma-crossover-balanced-v1` on
930 research bars and reserved 252 unopened holdout bars. Candidate OOS passed
with median Sharpe .945987 and profitable-window rate .666667. Nested OOS failed:
only 2 of all 6 windows were profitable (.333333 versus the unchanged .6 minimum).
Nested median Sharpe 1.114608 measures the three deployed windows; it does not
erase the three abstentions or establish whole-procedure robustness.

| Fold | Training period | Candidate OOS period | Training trades | OOS trades | OOS return | Sharpe | Sortino | Max DD | Nested decision |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 2021-09-08–2022-06-16 | 2022-06-17–2022-12-19 | 13 | 12 | -.008029 | -.840523 | -1.145369 | -.017658 | TRADE |
| 2 | 2022-06-17–2022-12-19 | 2022-12-20–2023-06-22 | 12 | 5 | .004906 | 1.163696 | 2.143584 | -.002559 | TRADE |
| 3 | 2022-12-20–2023-06-22 | 2023-06-23–2023-12-20 | 5 | 3 | .003197 | 1.398559 | 2.459542 | -.001727 | NO_TRADE |
| 4 | 2023-06-23–2023-12-20 | 2023-12-21–2024-06-24 | 3 | 5 | -.012522 | -3.012436 | -3.126535 | -.012522 | NO_TRADE |
| 5 | 2023-12-21–2024-06-24 | 2024-06-25–2024-12-20 | 5 | 11 | .008687 | .777366 | 1.206367 | -.006414 | NO_TRADE |
| 6 | 2024-06-25–2024-12-20 | 2024-12-23–2025-06-26 | 11 | 16 | .026847 | 1.114608 | 1.987465 | -.023656 | TRADE |

Training trade counts in folds 3–5 are below 10, consistent with abstention;
the historical nested artifact omitted detailed inner rejection fields, so other
causes are unknown. Separate validation slices, paid fees and monetary slippage
are not recorded in this IA artifact. Do not substitute BSX assumptions or claim zero
costs. The irregular calendar length of the first 126-observation training slice
also warrants provider-history coverage inspection in fresh research.

The existing v6 research workflow now diagnoses every candidate-OOS pass, even when
nested selection rejects the symbol, and includes a separate BSX/IA cohort at 10 bps
fees. Existing preregistered SMA, trend, breakout and mean-reversion families remain
unchanged. Fixed parameter probes and execution-cost stresses use only research bars;
regime descriptors use each fold's training prices. These diagnostics cannot select,
publish or promote a strategy. Real robustness results must come from the research run;
the historical candidate summaries alone do not establish parameter stability.

### Fresh sealed research: run 34915908321

The existing v6 workflow completed on 2026-09-15 using real Alpaca historical data.
Both the current 10-symbol Scanner reference universe and the BSX/IA cohort returned
zero pre-holdout candidates, zero operational failures and zero opened holdouts.
This is research evidence, not a production-cycle order authorization. The reference
universe retained its existing 1 bps fee assumption; BSX/IA used 10 bps. Both used
5 bps slippage and 2 bps market impact before fixed 1x/1.5x/2x cost stresses.

All 13 candidate-OOS passes across 7 symbols received parameter, execution-cost
and training-regime diagnostics. AAPL/AMZN breakout, AVGO mean reversion,
META breakout and baseline mean reversion, NFLX breakout, NVDA SMA and all four
BSX candidates passed the advisory parameter/execution probes. META and NFLX
mean-reversion-10-40-risk-v6 failed cost stress and parameter/drawdown robustness.
Probe success does not override nested or statistical rejection.

| Symbol | Candidate OOS passes | Nested Sharpe / .7 minimum | Profitable windows / .6 minimum | Blocking evidence |
|---|---:|---:|---:|---|
| AAPL | 1 | .601015 | .500000 | nested Sharpe and profitable rate |
| MSFT | 0 | .408523 | .333333 | candidate OOS; nested Sharpe and profitable rate |
| NVDA | 1 | 1.211550 | .666667 | full statistical validation |
| GOOGL | 0 | 1.093978 | .500000 | candidate OOS; nested profitable rate |
| AMZN | 1 | .429063 | .500000 | nested Sharpe and profitable rate |
| META | 3 | .604162 | .833333 | nested Sharpe; one candidate's cost/parameter probes |
| TSLA | 0 | -.932428 | .333333 | candidate OOS; nested Sharpe, profitable rate, PF .726994 < 1.1 |
| AMD | 0 | .655803 | .500000 | candidate OOS; nested Sharpe and profitable rate |
| AVGO | 1 | .465529 | .500000 | nested Sharpe and profitable rate |
| NFLX | 2 | .346919 | .666667 | nested Sharpe; one candidate's cost/parameter probes |
| BSX | 4 | -.309091 | .166667 | nested Sharpe, profitable rate, PF .897665 < 1.1 |
| IA | 0 | .358625 | .500000 | candidate OOS; nested Sharpe and profitable rate |

NVDA passed nested OOS, PBO and cost stress but failed adjusted p-value (.44159298),
deflated Sharpe probability (.54780637) and bootstrap/block-bootstrap lower bound
(-.00539661). It remains rejected; downstream holdout/promotion/Risk/Execution were
not evaluated. IA's old candidate pass did not repeat in this fresh cohort.

BSX's four candidate passes were trend-following-30-120-risk-v6,
mean-reversion-balanced-v1, mean-reversion-3-15-risk-v6 and sma-crossover-balanced-v1.
Nested selection traded in folds 1–3, then abstained in folds 4–6 because every
training candidate had fewer than 10 trades. The deployed windows had 21 trades in
total. IA abstained in folds 3–4 for the same observed training-trade gate and traded
in four windows (37 OOS trades). All per-candidate metrics, paid fees, assumed
slippage, parameters and gate values are retained in the workflow logs/artifact.
Monetary slippage remains explicitly unrecorded separately by the fill contract.

The 50/150 trend family cannot warm up inside a 126-bar training window, so its
zero-trade abstention is expected. A future preregistered study may compare longer
training horizons for slow-trend hypotheses; this round changes neither the horizon
nor a threshold in response to observed results. No strategy was tuned against
these findings or the sealed holdout.

## Integration proof and limits

The deterministic fixture runs actual Scanner evidence builders, Fundamental/Technical,
Manager BUY and bucket selection, candidate OOS and nested OOS, Portfolio contract,
Manager promotion filtering, Risk API, Execution API and the real Alpaca adapter with
MockTransport. Each repo runs in a separate process/container and serializes JSON.
Provider data, promotion record/storage, account state and broker HTTP are test doubles.
It is not a full Database promotion lifecycle or a real broker connectivity test.

Synthetic bars pass the unchanged backtest gates. The resulting evidence is marked
fixture-only, has no production authorization, and proves no profitability. Emergency
halt rejects; Manager replay and Execution replay send no second mock broker order.
The fixture forbids real socket connections.

It exposed two production integration bugs: Manager default protection omitted exit
side/symbol/quantity, and Execution batch replay resubmitted a persisted placed order.
Manager now derives absent fields from approved entry and rejects contradictory fields
or invalid/nonfinite bracket prices. Execution consults persisted state before broker
I/O and does not resubmit placed/partial/executed/cancelled or broker-identified orders.
This proves sequential replay safety, not a distributed concurrent-submission lock.

## Verification / remaining blockers

- Manager full local suite: 1297 passed.
- Scanner full existing CI unit/contract suite: 170 passed.
- Backtest full suite: 363 passed; branch coverage 90.78% meets the unchanged 90%
  gate; Ruff passed.
- Risk full suite: 103 passed.
- Execution full suite: 233 passed. No tests disabled or suite narrowed. Legacy failures
  covered explicit Risk approvals, mandatory bracket payloads, queued response assertions,
  wire enum values, route compatibility and deterministic processing/replay.
- Removed production synthesis of the magic test Risk approval. Explicit approvals now
  exist only inside test fixtures. Manager also rejects promotion records marked fixture-only,
  research-only or explicitly lacking production authorization.
- Fresh cross-repo fixture rerun passed all 11 checks after repairing the local Technical
  numba/llvmlite runtime and restoring missing dependencies. This is a new run against
  the current patches, not reuse of the earlier successful artifact. One mock broker order
  was accepted; exact replays generated zero duplicate mock submissions. Fresh clock,
  account, orders and positions reads are asserted before submission. No real socket is used.
- Git CLI lacked a credential in the restored environment. Publication uses the connected
  GitHub app in the explicitly authorized existing athipan1 repositories. Remote Git trees
  are compared against the tested local trees before opening PRs.

Remaining: verify Backtest research/CI, publish Manager and pass its existing cross-repo
CI against merged dependencies. Merge only after green, then run the existing Hourly
with Alpaca Paper `dry_run=false`; Execution requires a fresh broker-open clock before
any submission. Fixture results grant no production authorization.
Production still requires real evidence through every gate. Baseline result is healthy
NO_TRADE (10 Scanner, 9 score, 0 BUY, 0 broker orders); it is not a test failure.

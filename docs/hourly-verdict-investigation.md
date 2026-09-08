# Evidence-based verdicts and separate exact Backtest blockers

This continues Manager #439 and Scanner #40. Baseline is the actual Alpaca Paper
[run 34072289685](https://github.com/athipan1/Manager_Agent/actions/runs/34072289685),
cycle `hourly-paper-4fd6d3db930a-20260907T01`. Its 1,000-symbol universe produced
10 candidates and 10 successful deep analyses. All final ranking scores passed
0.55; all verdicts were HOLD. Ranking confidence is not directional evidence.

## Verified causes

Manager's unchanged directional aggregation is confidence × signed action ×
agent weight, followed by the asset bias multiplier. HOLD contributes zero.
BUY requires at least 0.2; strong BUY requires 0.8. It does not require unanimous
BUY: Technical BUY at 0.75 with Fundamental HOLD gives 0.375 with default weights.
Market Regime is a separate portfolio/risk gate, not another directional vote.
The baseline SPY regime was bull, low risk, normal routing; it did not veto BUY.

Technical requires price > SMA200, RSI < 30, and MACD > signal simultaneously.
The actual baseline failures are:

| Symbol | RSI | Failed BUY predicates |
|---|---:|---|
| WDC | 48.28 | RSI |
| JFIN | 24.56 | price/SMA200, MACD |
| YB | 49.46 | price/SMA200, RSI |
| ZJK | 58.59 | RSI |
| DCBO | 58.33 | RSI, MACD |
| NAGE | 48.39 | price/SMA200, RSI |
| IA | 40.87 | price/SMA200, RSI, MACD |
| QTTB | 29.11 | MACD |
| QQQX | 52.45 | RSI, MACD |
| TBLD | 44.67 | RSI, MACD |

These HOLD decisions agree with the implemented policy. Technical now returns
the observed fields, operators, thresholds and reason codes from the same
function that generates the signal. Its API model preserves that trace.

Fundamental had concrete input and fallback defects:

- Scanner revenue CAGR is decimal. The old adapter divided values > 1 by 100,
  fabricated four fiscal observations, then annualized the input again. WDC's
  0.2735046 became 0.083927; QTTB's 1.006606 became 0.003344.
- EPS/FCF total growth was treated as annual CAGR; FCF could substitute for OCF;
  percentage ROE/ROA/margins were passed into decimal scoring.
- Zero growth could trigger a higher-scoring fallback. Zero component scores
  were omitted from the weighted denominator, inflating weak evidence.
- Optional LLM results could replace deterministic action/score; optional model
  failure could switch scoring engines. Prefetched provenance was understated.

Scanner now carries real dated fiscal observations and explicit decimal units.
Fundamental computes growth from the actual date span, retains zero/negative
evidence and zero-score weights, never creates fiscal history or substitutes
cash-flow types, and restricts the LLM to supplementary reasoning. Legacy or
stale prefetched history cannot authorize a Fundamental BUY. Existing source
conflict vetoes and severe flags remain effective. The BUY threshold stays 0.72.

Manager now records raw/normalized actions, explicit invalid-action fallbacks,
agent decision traces and the actual aggregate. Changed Scanner evidence or
weights invalidate the one-shot deep-analysis cache. Invalid/nonfinite scores
contribute zero; missing Fundamental confidence cannot borrow Scanner's score.

## Exact Backtest is an independent blocker

All five research symbols generated trades, with fee 10 bps/side and slippage
5 bps. Research-period returns and drawdowns below are decimal fractions.

| Symbol | Research bars | Trades | Return | Sharpe | Sortino | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| QTTB | 1002 | 158 | -0.000214 | 0.012524 | 0.018721 | -0.044908 |
| JFIN | 941 | 152 | 0.019364 | 0.196505 | 0.280768 | -0.036209 |
| NAGE | 1002 | 177 | -0.010979 | -0.090330 | -0.138533 | -0.039256 |
| DCBO | 1002 | 33 | -0.016614 | -0.259636 | -0.343676 | -0.027247 |
| IA | 930 | 101 | 0.042881 | 0.400690 | 0.575436 | -0.033715 |

The nested outer OOS profitable-window rates were 1/3, 1/3, 1/3, 0 and 1/3,
all below 0.6. Candidate OOS and nested outer OOS are separate tests: IA passed
the former and failed the latter. QTTB/JFIN/NAGE/IA really were selected by the
latest training window. The old message incorrectly attributed any promotion
failure to latest-window nonselection. Backtest now reports nested OOS failures
separately and emits latest-window rejection only when selection actually fails.
Eligibility rules are unchanged. The 252-bar holdout stayed sealed; downstream
robustness/holdout checks were not reached and cannot be reported as passes.

## Cycle artifacts and verification

The existing Hourly workflow emits `hourly-decision-trace.json` and `.md` next
to the selection funnel. Each analyzed symbol has independent `scanner_pass`,
`score_pass`, `verdict_pass`, `allocation_pass`, `backtest_pass`, `risk_pass` and
`execution_authorized` fields. Unknown/not-evaluated values are null, never
approval. Each rejection retains symbol, score, threshold, gate, reason code
and readable reason. Exact Backtest details include costs, history, actual
metrics, candidate/nested OOS, latest training selection and promotion status.

`scripts/run_decision_contract_e2e.py` executes the four repositories in separate
runtimes with JSON handoffs. Labelled deterministic provider fixtures produce
real computed RSI/MACD and fiscal metrics. It proves evidence can generate BUY,
negative OCF and insufficient bars fail closed, and HOLD scores cannot create
BUY. It grants no broker authority and runs in the existing Agent Contract E2E.
The separate Hourly workflow uses real providers and Alpaca Paper credentials.

No Risk, exposure, Backtest, reconciliation, emergency-halt or duplicate-order
protection is bypassed. A new real cycle may correctly remain NO_TRADE.

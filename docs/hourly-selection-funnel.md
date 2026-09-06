# Hourly selection funnel and verified baseline

Baseline: Manager commit 7db4e6cf451a0b0295497eb4d44e22c42d004be4,
[Hourly run 34048034076](https://github.com/athipan1/Manager_Agent/actions/runs/34048034076),
cycle `hourly-paper-4fd6d3db930a-20260906T17`.

The real-market artifact contains 1,000 universe symbols, 984 successful broad
fundamental analyses, 16 provider errors, 10 Scanner candidates, 9 research
candidates, and 10 successful Technical/Fundamental analyses. All ten final
opportunity scores (0.5778–0.6150) exceed 0.55, but all final verdicts are HOLD.
Allocation requires BUY/STRONG_BUY as well as score and classification evidence.
Four symbols also require bucket/evidence review. Allocation and exposure input
are zero. This is not evidence that min_final_score is too high.

The research lane separately sends QTTB, JFIN, BANX, DCBO and IA to exact
Backtest. All five return no_eligible_strategy. YB and ZJK have 340 and 485 bars,
below the 882-bar nested research plus sealed holdout history requirement.
The execution cycle also records market_closed. Research eligibility does not
authorize a production allocation or order.

The current route is /discover-best-fundamentals. It uses weighted fundamental
ranking followed by production-first enrichment. It does not invoke the other
Scanner route's market prefilter, market ranker or BUY/STRONG_BUY requirement.
Therefore prefilter_count and ranked_market_count are null with not_in_route,
not invented counts. fundamental_ranked_count measures the active route.
Universe benchmark sources returned 403 and used declared priority fallbacks;
Nasdaq Trader still supplied the broad listed universe. This degraded coverage
is reported separately from candidate selection.

## New artifacts

`hourly-selection-funnel.json` and `.md` are built after final reconciliation and
before the existing artifact upload, including controlled NO_TRADE cycles. The
JSON contains all fourteen requested counters, stage status, source run/cycle,
per-symbol rejection rows, analysis outcomes and Backtest validation thresholds.
Missing data remains null. A missing source or mismatched Backtest cycle cannot
be reported as a successful no-trade verification.

Scanner records every symbol excluded by provider failure/defer, fundamental
rank cutoff, or post-enrichment candidate limit. Manager records every failed
entry predicate without changing its decision. The old profitability report now
separates scanner_candidate_count from opportunity-qualified production count.

Rejection fields: symbol, score, threshold, gate, reason_code, reason, observed,
lane. Several failures may apply to one symbol. Counts are symbol counts, not
rejection event counts. Market-session and research Backtest blockers may coexist
with production allocation rejection; a later gate never erases earlier evidence.

## Verification

Run existing allocation, preselection, analysis, exposure and funnel tests plus
`tests/test_selection_funnel.py`. Replay a downloaded artifact directory:

```bash
python scripts/build_selection_funnel.py --reports-dir reports --source-run-id 34048034076
```

No score, confidence, BUY requirement, exposure, Backtest or Risk threshold is
changed. Reconciliation, emergency halt and duplicate-order protection remain
on their existing execution path. The diagnostics have no order authority.

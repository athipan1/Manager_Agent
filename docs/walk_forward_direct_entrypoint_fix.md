# Walk-Forward Direct Entrypoint Fix

Hourly Auto Trading invokes the Backtest verifier as a file:

```text
python scripts/verify_backtest_publish.py reports/hourly-backtest-result.json
```

For direct file execution, Python places the `scripts` directory at the front of `sys.path`. The Walk-forward runner uses package imports such as:

```python
from scripts.run_multi_strategy_backtests import ...
```

Without the repository root on `sys.path`, the package name `scripts` cannot be resolved. The verifier failed before the temporary Backtest API started, so no `backtest-agent-api.log` or Walk-forward report was produced. The artifact therefore retained the preceding fixed-strategy report.

The verifier now inserts its repository root before importing orchestration modules. This keeps direct GitHub Actions execution consistent with pytest and `python -m scripts.verify_backtest_publish` execution.

A subprocess regression test starts from the `scripts` directory, imports the verifier as a direct-entrypoint module, and confirms that the package-scoped Walk-forward runner is reachable.

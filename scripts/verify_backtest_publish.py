from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict


def unwrap_backtest_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return BacktestRunAndPublishResult from a standard or legacy response."""
    data = report.get("data")
    return data if isinstance(data, dict) else report


def verify_backtest_publish(report: Dict[str, Any]) -> Dict[str, Any]:
    data = unwrap_backtest_report(report)
    published = data.get("published")
    publish_status = data.get("publish_status")
    if published is not True or publish_status != "success":
        raise ValueError(
            "Backtest result was not stored in Database_Agent: "
            f"published={published} publish_status={publish_status}"
        )

    database_response = data.get("database_response") or {}
    if not isinstance(database_response, dict) or database_response.get("status") != "success":
        raise ValueError(f"Database_Agent rejected Backtest result: {database_response}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Backtest_Agent database publishing")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if not args.report.exists():
        raise SystemExit(f"Backtest report was not created: {args.report}")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    try:
        data = verify_backtest_publish(report)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    result = data.get("result") or {}
    print(
        "Backtest stored successfully: "
        f"strategy={result.get('strategy')} symbols={result.get('symbols')} "
        f"trade_count={(result.get('metrics') or {}).get('trade_count')}"
    )


if __name__ == "__main__":
    main()

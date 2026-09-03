#!/usr/bin/env python3
"""Resolve whether the hourly workflow may call Manager/Risk/Execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def normalized_symbol(value: Any) -> str:
    return str(value or "").strip().upper()[:16]


def unwrap_backtest_report(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = as_dict(report)
    for _ in range(3):
        inner = payload.get("data")
        if not isinstance(inner, Mapping):
            break
        candidate = as_dict(inner)
        if any(
            key in candidate
            for key in (
                "eligible_symbols",
                "eligible_count",
                "items",
                "all_succeeded",
                "selection_complete",
            )
        ):
            payload = candidate
            break
        payload = candidate
    return payload


def eligible_symbols(report: Mapping[str, Any]) -> list[str]:
    data = unwrap_backtest_report(report)
    if data.get("all_succeeded") is not True:
        raise ValueError("Backtest report did not prove all symbols succeeded")
    if data.get("selection_complete") is not True:
        raise ValueError("Backtest strategy selection is incomplete")

    symbols: list[str] = []
    raw_symbols = data.get("eligible_symbols")
    if isinstance(raw_symbols, list):
        for raw in raw_symbols:
            symbol = normalized_symbol(raw)
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    else:
        for item in as_list(data.get("items")):
            row = as_dict(item)
            if row.get("status") != "eligible_strategy_found":
                continue
            symbol = normalized_symbol(row.get("symbol"))
            if symbol and symbol not in symbols:
                symbols.append(symbol)

    if "eligible_count" in data:
        try:
            expected = int(data.get("eligible_count"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Backtest eligible_count is invalid") from exc
        if expected != len(symbols):
            raise ValueError("Backtest eligible_count does not match eligible_symbols")
    return symbols


def trade_gate_diagnostics(
    preflight: Mapping[str, Any], backtest_report: Mapping[str, Any], symbols: list[str]
) -> dict[str, Any]:
    data = unwrap_backtest_report(backtest_report)
    runtime = as_dict(preflight.get("runtime"))
    items = as_list(data.get("items"))
    return {
        "market_open": preflight.get("market_open") is True,
        "market_mode": preflight.get("market_mode"),
        "paper_automation": runtime.get("paper_automation") is True,
        "backtest_tested_count": len(items),
        "backtest_eligible_count": len(symbols),
        "eligible_symbols": symbols,
    }


def resolve_trade_gate(
    preflight: Mapping[str, Any], backtest_report: Mapping[str, Any]
) -> dict[str, Any]:
    if preflight.get("status") != "ready" or not preflight.get(
        "portfolio_cycle_id"
    ):
        raise ValueError("Hourly preflight must be ready before trade gating")

    runtime = as_dict(preflight.get("runtime"))
    paper_automation = runtime.get("paper_automation") is True
    symbols = eligible_symbols(backtest_report)
    diagnostics = trade_gate_diagnostics(preflight, backtest_report, symbols)

    if paper_automation and preflight.get("market_open") is not True:
        return {
            "should_trade": False,
            "reason": "market_closed",
            "next_action": "WAIT_FOR_REGULAR_SESSION",
            "eligible_symbols": symbols,
            "diagnostics": diagnostics,
        }
    if not symbols:
        return {
            "should_trade": False,
            "reason": "no_eligible_strategy",
            "next_action": "REVIEW_BACKTEST_REJECTIONS",
            "eligible_symbols": [],
            "diagnostics": diagnostics,
        }
    return {
        "should_trade": True,
        "reason": "eligible_strategy_available",
        "next_action": "CALL_MANAGER_RISK_EXECUTION",
        "eligible_symbols": symbols,
        "diagnostics": diagnostics,
    }


def build_no_trade_report(
    preflight: Mapping[str, Any],
    gate: Mapping[str, Any],
    backtest_report: Mapping[str, Any],
) -> dict[str, Any]:
    reason = str(gate.get("reason") or "")
    if gate.get("should_trade") is not False or reason not in {
        "market_closed",
        "no_eligible_strategy",
    }:
        raise ValueError("A no-trade report requires a controlled no-trade gate")

    data = unwrap_backtest_report(backtest_report)
    symbols = [
        normalized_symbol(symbol)
        for symbol in as_list(gate.get("eligible_symbols"))
        if normalized_symbol(symbol)
    ]
    diagnostics = as_dict(gate.get("diagnostics"))
    return {
        "schema_version": "hourly-manager-cycle.no-trade.v1",
        "status": "success",
        "execute_requested": False,
        "market_mode": preflight.get("market_mode"),
        "reason": reason,
        "next_action": gate.get("next_action"),
        "broker_orders_submitted": False,
        "trade_gate": {
            "should_trade": False,
            "reason": reason,
            "next_action": gate.get("next_action"),
            "market_open": diagnostics.get("market_open"),
            "paper_automation": diagnostics.get("paper_automation"),
            "backtest_tested_count": diagnostics.get("backtest_tested_count", 0),
            "backtest_eligible_count": diagnostics.get("backtest_eligible_count", 0),
            "eligible_symbols": symbols,
        },
        "manager_response": {
            "status": "success",
            "data": {
                "scanner_count": len(as_list(data.get("items"))),
                "selected_positions": [{"symbol": symbol} for symbol in symbols],
                "execution": {
                    "status": "not_attempted",
                    "reason": reason,
                    "created": [],
                    "broker_orders_submitted": False,
                },
                "portfolio_summary": {
                    "approved_positions": 0,
                    "execution_status": "not_attempted",
                },
            },
        },
        "safety": {
            "risk_called": False,
            "execution_called": False,
            "broker_orders_submitted": False,
        },
    }


def write_github_output(path: Path | None, gate: Mapping[str, Any]) -> None:
    if path is None:
        return
    diagnostics = as_dict(gate.get("diagnostics"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            "should_trade="
            + ("true" if gate.get("should_trade") is True else "false")
            + "\n"
        )
        handle.write(f"reason={gate.get('reason')}\n")
        handle.write(f"next_action={gate.get('next_action')}\n")
        handle.write(
            f"eligible_count={len(as_list(gate.get('eligible_symbols')))}\n"
        )
        handle.write(
            "market_open="
            + ("true" if diagnostics.get("market_open") is True else "false")
            + "\n"
        )
        handle.write(
            f"backtest_tested_count={int(diagnostics.get('backtest_tested_count', 0))}\n"
        )
        handle.write(
            f"backtest_eligible_count={int(diagnostics.get('backtest_eligible_count', 0))}\n"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight", type=Path, default=Path("reports/hourly-preflight.json")
    )
    parser.add_argument(
        "--backtest", type=Path, default=Path("reports/hourly-backtest-result.json")
    )
    parser.add_argument(
        "--manager-output",
        type=Path,
        default=Path("reports/hourly-manager-cycle.json"),
    )
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    backtest_report = json.loads(args.backtest.read_text(encoding="utf-8"))
    gate = resolve_trade_gate(preflight, backtest_report)
    write_github_output(args.github_output, gate)
    diagnostics = as_dict(gate.get("diagnostics"))
    if gate["should_trade"] is False:
        report = build_no_trade_report(preflight, gate, backtest_report)
        args.manager_output.parent.mkdir(parents=True, exist_ok=True)
        args.manager_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            "Controlled no-trade gate recorded: "
            f"reason={gate['reason']} "
            f"next_action={gate['next_action']} "
            f"market_open={diagnostics.get('market_open')} "
            f"backtest_tested_count={diagnostics.get('backtest_tested_count')} "
            f"eligible_count={len(gate['eligible_symbols'])}"
        )
    else:
        print(
            "Hourly trade gate passed: "
            f"next_action={gate['next_action']} "
            f"backtest_tested_count={diagnostics.get('backtest_tested_count')} "
            f"eligible_count={len(gate['eligible_symbols'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

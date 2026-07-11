from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List

CONFIRMATION_PHRASE = "EXECUTE_PAPER_PROTECTION_RECONCILIATION"


def _request_json(
    base_url: str,
    path: str,
    payload: Dict[str, Any],
    *,
    api_key: str,
    timeout: int = 180,
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        raise RuntimeError(
            f"Execution_Agent returned HTTP {exc.code}: {raw}"
        ) from exc


def _unwrap(value: Dict[str, Any]) -> Dict[str, Any]:
    data = value.get("data")
    return data if isinstance(data, dict) else value


def _load_proposals(raw_json: str | None, file_path: str | None) -> List[Dict[str, Any]]:
    if file_path:
        raw = Path(file_path).read_text(encoding="utf-8")
    else:
        raw = raw_json or "[]"
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("risk proposals must be a JSON list")
    return [item for item in value if isinstance(item, dict)]


def _normalize_symbols(values: Iterable[str]) -> List[str]:
    symbols: List[str] = []
    for value in values:
        for token in str(value or "").split(","):
            symbol = token.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def build_execution_payload(
    preview_response: Dict[str, Any],
    *,
    proposals: List[Dict[str, Any]],
    symbols: List[str],
    confirmation_phrase: str,
    allow_multi_symbol: bool,
) -> Dict[str, Any]:
    preview = _unwrap(preview_response)
    ticket = preview.get("ticket") if isinstance(preview.get("ticket"), dict) else {}
    ticket_id = str(ticket.get("ticket_id") or "").strip()
    if not ticket_id:
        raise ValueError("preview did not return a reconciliation ticket")
    if confirmation_phrase != CONFIRMATION_PHRASE:
        raise ValueError("confirmation phrase does not match")
    if not symbols:
        raise ValueError("at least one symbol must be selected")
    if len(symbols) > 1 and not allow_multi_symbol:
        raise ValueError("multi-symbol execution requires --allow-multi-symbol")
    return {
        "risk_proposals": proposals,
        "symbols": symbols,
        "reconciliation_ticket_id": ticket_id,
        "execution_confirmation_phrase": confirmation_phrase,
        "execute_paper": True,
        "allow_multi_symbol": allow_multi_symbol,
        "source": "manager-agent-protection-reconciliation-client",
    }


def run(
    *,
    execution_url: str,
    api_key: str,
    proposals: List[Dict[str, Any]],
    symbols: List[str],
    execute_paper: bool,
    confirmation_phrase: str,
    allow_multi_symbol: bool,
) -> Dict[str, Any]:
    preview_payload = {"risk_proposals": proposals}
    preview_response = _request_json(
        execution_url,
        "/broker/protection-reconciliation/preview",
        preview_payload,
        api_key=api_key,
    )
    result: Dict[str, Any] = {
        "status": "preview_only",
        "orders_changed": False,
        "preview": preview_response,
    }
    if not execute_paper:
        return result

    execution_payload = build_execution_payload(
        preview_response,
        proposals=proposals,
        symbols=symbols,
        confirmation_phrase=confirmation_phrase,
        allow_multi_symbol=allow_multi_symbol,
    )
    execution_response = _request_json(
        execution_url,
        "/broker/protection-reconciliation/execute",
        execution_payload,
        api_key=api_key,
    )
    result.update(
        {
            "status": "execution_requested",
            "execution_payload": execution_payload,
            "execution": execution_response,
            "orders_changed": bool(
                _unwrap(execution_response).get("orders_changed")
            ),
        }
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or execute approved Alpaca Paper protection reconciliation."
    )
    parser.add_argument("--execution-url", default="http://execution-agent:8006")
    parser.add_argument("--api-key", default="dev_execution_key")
    parser.add_argument("--risk-proposals-json")
    parser.add_argument("--risk-proposals-file")
    parser.add_argument("--symbols", action="append", default=[])
    parser.add_argument("--execute-paper", action="store_true")
    parser.add_argument("--confirmation-phrase", default="")
    parser.add_argument("--allow-multi-symbol", action="store_true")
    parser.add_argument("--output-json")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        proposals = _load_proposals(
            args.risk_proposals_json, args.risk_proposals_file
        )
        result = run(
            execution_url=args.execution_url,
            api_key=args.api_key,
            proposals=proposals,
            symbols=_normalize_symbols(args.symbols),
            execute_paper=args.execute_paper,
            confirmation_phrase=args.confirmation_phrase,
            allow_multi_symbol=args.allow_multi_symbol,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 1

    rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print(rendered)
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

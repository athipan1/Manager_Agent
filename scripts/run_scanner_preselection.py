from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _request_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(
            f"Scanner preselection returned HTTP {exc.code}: {body}"
        ) from exc


def extract_backtest_symbols(response: Dict[str, Any]) -> List[str]:
    if response.get("status") != "success":
        raise ValueError(f"Scanner preselection failed: {response}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError("Scanner preselection response has no data object")
    positions = data.get("pre_backtest_selected_positions") or []
    return list(
        dict.fromkeys(
            str(item.get("symbol") or item.get("ticker") or "").upper()
            for item in positions
            if isinstance(item, dict)
            and str(item.get("symbol") or item.get("ticker") or "").strip()
        )
    )


def _payload_from_env() -> Dict[str, Any]:
    return {
        "account_id": 1,
        "max_universe": int(os.getenv("MAX_UNIVERSE", "1000")),
        "top_n": int(os.getenv("TOP_N", "10")),
        "exchange": "NASDAQ",
        "max_workers": 10,
        "min_final_score": float(os.getenv("MIN_FINAL_SCORE", "0.55")),
        "execute": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Scanner discovery without Risk or Execution."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/discover-analyze-trade",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    payload = _payload_from_env()
    response = _request_json(args.url, payload, args.timeout)
    symbols = extract_backtest_symbols(response)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "scanner_preselection",
        "request": payload,
        "response": response,
        "backtest_symbols": symbols,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"backtest_symbols={','.join(symbols)}\n")
    print(
        "Scanner preselection complete: "
        f"symbols={','.join(symbols) if symbols else '<none>'}"
    )


if __name__ == "__main__":
    main()

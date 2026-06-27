from __future__ import annotations

from pathlib import Path

WORKFLOW = Path("app/workflows/discovery_workflow.py")

IMPORT_OLD = "from ..services.context_service import fetch_context_value, fetch_session_risk_contexts\n"
IMPORT_NEW = (
    "from ..services.context_service import fetch_context_value, fetch_session_risk_contexts\n"
    "from ..services.curator_signal_service import enrich_payloads_with_curator_signals\n"
)

PAYLOAD_OLD = "            position_analysis_payloads = allocation_report.get(\"position_analysis_payloads\") or []\n"
PAYLOAD_NEW = (
    "            position_analysis_payloads = allocation_report.get(\"position_analysis_payloads\") or []\n"
    "            position_analysis_payloads, curator_signals = await enrich_payloads_with_curator_signals(\n"
    "                payloads=position_analysis_payloads,\n"
    "                correlation_id=correlation_id,\n"
    "            )\n"
)

PERSIST_OLD = (
    "                        \"skipped_existing_protected_position\": item[\"symbol\"] in {row[\"symbol\"] for row in skipped_existing_protected_positions},\n"
)
PERSIST_NEW = (
    "                        \"skipped_existing_protected_position\": item[\"symbol\"] in {row[\"symbol\"] for row in skipped_existing_protected_positions},\n"
    "                        \"curator_signal\": {\n"
    "                            row.get(\"symbol\"): row for row in curator_signals\n"
    "                        }.get(item[\"symbol\"]),\n"
)

DATA_OLD = "            \"skipped_existing_protected_positions\": skipped_existing_protected_positions,\n"
DATA_NEW = (
    "            \"skipped_existing_protected_positions\": skipped_existing_protected_positions,\n"
    "            \"curator_signals\": curator_signals,\n"
)

SUMMARY_OLD = "                \"skipped_existing_protected_positions\": len(skipped_existing_protected_positions),\n"
SUMMARY_NEW = (
    "                \"skipped_existing_protected_positions\": len(skipped_existing_protected_positions),\n"
    "                \"curator_signals\": len(curator_signals),\n"
)


def replace_once(content: str, old: str, new: str, label: str) -> str:
    if new in content:
        return content
    if old not in content:
        raise RuntimeError(f"Could not find patch anchor: {label}")
    return content.replace(old, new, 1)


def main() -> int:
    content = WORKFLOW.read_text(encoding="utf-8")
    content = replace_once(content, IMPORT_OLD, IMPORT_NEW, "curator import")
    content = replace_once(content, PAYLOAD_OLD, PAYLOAD_NEW, "position payload enrichment")
    content = replace_once(content, PERSIST_OLD, PERSIST_NEW, "persist_signal curator metadata")
    content = replace_once(content, DATA_OLD, DATA_NEW, "response curator_signals")
    content = replace_once(content, SUMMARY_OLD, SUMMARY_NEW, "portfolio summary curator count")
    WORKFLOW.write_text(content, encoding="utf-8")
    print("Applied Curator advisory wiring patch to app/workflows/discovery_workflow.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

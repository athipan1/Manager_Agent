import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

# GitHub Actions invokes this file as `python scripts/render_hourly_portfolio_report.py`.
# In that execution mode Python puts `scripts/` on sys.path, not the repository
# root, so imports from `app` fail unless the root is added explicitly.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

try:
    from scripts.render_hourly_portfolio_report_legacy import *  # noqa: F401,F403
    import scripts.render_hourly_portfolio_report_legacy as _legacy
    from scripts.liquidity_coverage import enrich_hourly_artifact
except ModuleNotFoundError:
    from render_hourly_portfolio_report_legacy import *  # type: ignore # noqa: F401,F403
    import render_hourly_portfolio_report_legacy as _legacy  # type: ignore
    from liquidity_coverage import enrich_hourly_artifact  # type: ignore


def _load_curator_summarizer():
    """Load the pure report helper without requiring the FastAPI runtime.

    The hourly workflow renders reports on the GitHub runner after the trading
    stack has finished. That runner intentionally does not install the
    Manager application dependencies, so importing ``app.services`` would run
    ``app/__init__.py`` and fail when FastAPI is unavailable. The observability
    module itself only uses the Python standard library and is safe to load
    directly in that environment.
    """
    try:
        from app.services.curator_observability import summarize_curator_signals

        return summarize_curator_signals
    except ModuleNotFoundError as exc:
        if exc.name != "fastapi":
            raise

    module_path = (
        _REPOSITORY_ROOT / "app" / "services" / "curator_observability.py"
    )
    spec = importlib.util.spec_from_file_location(
        "manager_curator_observability_report_helper",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"unable to load curator report helper from {module_path}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.summarize_curator_signals


summarize_curator_signals = _load_curator_summarizer()


_legacy_render_curator_signals = _legacy.render_curator_signals
_legacy_render_portfolio_section = _legacy.render_portfolio_section


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _coverage_percent(summary: Dict[str, Any], key: str) -> str:
    pct_key = f"{key}_pct"
    if summary.get(pct_key) is not None:
        try:
            return f"{float(summary[pct_key]):.1f}%"
        except (TypeError, ValueError):
            pass
    return _percent(summary.get(key))


def render_liquidity_coverage(
    lines: List[str],
    summary: Dict[str, Any],
) -> None:
    if not isinstance(summary, dict) or not summary:
        return

    total = int(summary.get("candidate_count") or 0)
    adv_count = int(
        summary.get("average_daily_volume_available_count") or 0
    )
    dollar_count = int(
        summary.get("average_dollar_volume_available_count") or 0
    )
    spread_count = int(summary.get("spread_available_count") or 0)

    lines.append("## Liquidity Evidence Coverage")
    lines.append(f"- Summary Version: `{summary.get('summary_version', '-')}`")
    lines.append(f"- Population: `{summary.get('population', '-')}`")
    lines.append(f"- Candidates: `{total}`")
    lines.append(
        f"- Average Daily Volume: `{adv_count}/{total}` "
        f"(`{_coverage_percent(summary, 'average_daily_volume_coverage')}`)"
    )
    lines.append(
        f"- Average Dollar Volume: `{dollar_count}/{total}` "
        f"(`{_coverage_percent(summary, 'average_dollar_volume_coverage')}`)"
    )
    lines.append(
        f"- Bid/Ask Spread: `{spread_count}/{total}` "
        f"(`{_coverage_percent(summary, 'spread_coverage')}`)"
    )
    lines.append(
        "- Average Dollar Volume Required-Gate Readiness: "
        f"`{'eligible' if summary.get('average_dollar_volume_required_gate_ready') else 'not_ready'}`"
    )
    lines.append(
        "- Spread Required-Gate Readiness: "
        f"`{'eligible' if summary.get('spread_required_gate_ready') else 'not_ready'}`"
    )
    lines.append(
        "- Evidence Versions: "
        f"`{json.dumps(summary.get('liquidity_evidence_version_counts') or {}, ensure_ascii=False, sort_keys=True)}`"
    )
    lines.append(
        "- Evidence Statuses: "
        f"`{json.dumps(summary.get('liquidity_evidence_status_counts') or {}, ensure_ascii=False, sort_keys=True)}`"
    )
    lines.append(
        "- Quote Sources: "
        f"`{json.dumps(summary.get('quote_source_counts') or {}, ensure_ascii=False, sort_keys=True)}`"
    )
    lines.append(f"- Safety: `{summary.get('safety_note', '-')}`")
    lines.append("")


def render_portfolio_section(lines: List[str], data: Dict[str, Any]) -> None:
    _legacy_render_portfolio_section(lines, data)
    render_liquidity_coverage(
        lines,
        data.get("liquidity_coverage_summary") or {},
    )


def render_curator_signals(lines: List[str], data: Dict[str, Any]) -> None:
    curator_signals = _legacy._list(data.get("curator_signals"))
    if not curator_signals:
        return

    summary = data.get("curator_ensemble_summary")
    if not isinstance(summary, dict):
        summary = summarize_curator_signals(curator_signals)
    if summary.get("mode") != "shadow_ensemble":
        _legacy_render_curator_signals(lines, data)
        return

    counts = _legacy._dict(summary.get("signal_counts"))
    rows = _legacy._list(summary.get("rows"))
    lines.append("## Curator Shadow Ensemble")
    lines.append("- Deployment Mode: `advisory`")
    lines.append(
        f"- Observations: `{summary.get('ensemble_observations', 0)}`"
    )
    lines.append(
        f"- Available / Unavailable: `{summary.get('available', 0)}` / "
        f"`{summary.get('unavailable', 0)}`"
    )
    lines.append(
        f"- Availability Rate: `{_percent(summary.get('availability_rate'))}`"
    )
    lines.append(
        f"- Contract Valid / Invalid: `{summary.get('contract_valid', 0)}` / "
        f"`{summary.get('contract_invalid', 0)}`"
    )
    lines.append(
        f"- Contract Valid Rate: "
        f"`{_percent(summary.get('contract_valid_rate'))}`"
    )
    lines.append(
        f"- Unsafe Contracts: `{summary.get('unsafe_contract_count', 0)}`"
    )
    lines.append(
        f"- BUY / HOLD / SELL: `{counts.get('buy', 0)}` / "
        f"`{counts.get('hold', 0)}` / `{counts.get('sell', 0)}`"
    )
    lines.append(
        f"- Average Agreement: "
        f"`{_percent(summary.get('average_agreement'))}`"
    )
    lines.append(
        f"- Would Pass Required Gate: "
        f"`{summary.get('would_pass_required_gate', 0)}`"
    )
    lines.append(
        f"- Would Be Blocked: `{summary.get('would_be_blocked', 0)}`"
    )
    lines.append(
        f"- Required Mode Readiness: "
        f"`{'eligible' if summary.get('required_mode_eligible') else 'not_ready'}`"
    )
    lines.append(
        f"- Observation Progress: `{summary.get('ensemble_observations', 0)}` / "
        f"`{summary.get('observation_target', 50)}`"
    )
    lines.append(
        "- Safety: `Risk_Agent remains mandatory; direct execution forbidden`"
    )
    lines.append("")

    lines.append(
        "| Symbol | Status | Signal | Agreement | Contract | Would Pass | "
        "Skills | Rejection Codes |"
    )
    lines.append("|---|---|---|---:|---|---|---:|---|")
    for row in rows:
        row = _legacy._dict(row)
        codes = row.get("rejection_codes") or []
        code_text = ", ".join(str(code) for code in codes) if codes else "-"
        contract = row.get("contract_valid")
        contract_text = (
            "valid"
            if contract is True
            else "invalid"
            if contract is False
            else "-"
        )
        pass_gate = row.get("would_pass_required_gate")
        pass_text = (
            "yes"
            if pass_gate is True
            else "no"
            if pass_gate is False
            else "-"
        )
        lines.append(
            f"| {row.get('symbol', '-')} | {row.get('status', '-')} | "
            f"{row.get('signal', '-')} | {_percent(row.get('agreement'))} | "
            f"{contract_text} | {pass_text} | "
            f"{row.get('selected_skill_count', 0)} | {code_text} |"
        )
    lines.append("")


def render_order_review_approval_ticket(
    lines: List[str],
    ticket_response: Dict[str, Any],
) -> None:
    if not ticket_response:
        return

    ticket = _legacy.unwrap_data(ticket_response) or {}
    if not isinstance(ticket, dict):
        return
    summary = _legacy._dict(ticket.get("summary"))
    ready = _legacy._list(ticket.get("ready_for_manual_approval"))
    no_action = _legacy._list(ticket.get("no_action_required"))
    blocked = _legacy._list(ticket.get("blocked"))
    if not summary and not ready and not no_action and not blocked:
        return

    ticket_status = ticket.get("ticket_status", "-")
    requires_attention = ticket.get(
        "requires_operator_attention",
        summary.get("requires_operator_attention", False),
    )

    lines.append("## Broker Order Review Approval Ticket")
    lines.append(f"- Mode: `{ticket.get('mode', '-')}`")
    lines.append(f"- Safety: `{ticket.get('safety', '-')}`")
    lines.append(f"- Ticket ID: `{ticket.get('ticket_id', '-')}`")
    lines.append(f"- Ticket Status: `{ticket_status}`")
    lines.append(f"- Requires Operator Attention: `{requires_attention}`")
    lines.append(
        f"- Approval Required: `{ticket.get('approval_required', False)}`"
    )
    lines.append(
        f"- Execution Enabled: `{ticket.get('execution_enabled', False)}`"
    )
    lines.append(
        f"- Manual Confirmation Phrase: "
        f"`{ticket.get('manual_confirmation_phrase', '-')}`"
    )
    lines.append(
        f"- Requested Symbols: "
        f"`{', '.join(ticket.get('requested_symbols') or []) or '-'}`"
    )
    lines.append(
        f"- Ready For Manual Approval: "
        f"`{summary.get('ready_for_manual_approval_count', len(ready))}`"
    )
    lines.append(
        f"- No Action Required: "
        f"`{summary.get('no_action_required_count', len(no_action))}`"
    )
    lines.append(
        f"- Blocked: `{summary.get('blocked_count', len(blocked))}`"
    )
    lines.append(f"- Next Step: `{ticket.get('next_step', '-')}`")
    lines.append(
        f"- Orders Submitted By Ticket: "
        f"`{summary.get('orders_submitted', False)}`"
    )
    lines.append(
        f"- Orders Cancelled By Ticket: "
        f"`{summary.get('orders_cancelled', False)}`"
    )
    lines.append("")

    if ready:
        lines.append("### Ready For Manual Approval")
        lines.append(
            "| Symbol | Qty | Current Stop Order | Stop | TP | R/R | "
            "Approval Status | Proposed Actions |"
        )
        lines.append("|---|---:|---|---:|---:|---:|---|---:|")
        for row in ready:
            row = _legacy._dict(row)
            actions = _legacy._list(row.get("proposed_actions"))
            status = row.get("approval_status", "manual_approval_required")
            lines.append(
                f"| {row.get('symbol', '-')} | "
                f"{row.get('position_qty', '-')} | "
                f"{row.get('current_stop_order_id', '-')} | "
                f"{row.get('stop_price', '-')} | "
                f"{row.get('take_profit_price', '-')} | "
                f"{row.get('reward_risk_ratio', '-')} | "
                f"{_legacy._status_icon(status)} `{status}` | "
                f"{len(actions)} |"
            )
        lines.append("")

    if no_action:
        lines.append("### No Action Required")
        lines.append("| Symbol | Status | Reason | Recommended Next Step |")
        lines.append("|---|---|---|---|")
        for row in no_action:
            row = _legacy._dict(row)
            status = row.get("preview_status", "no_action_required")
            lines.append(
                f"| {row.get('symbol', '-')} | "
                f"{_legacy._status_icon(status)} `{status}` | "
                f"{row.get('reason', '-')} | "
                f"{row.get('recommended_next_step', '-')} |"
            )
        lines.append("")

    if blocked:
        lines.append("### Blocked Approval Ticket Items")
        lines.append("| Symbol | Status | Reason | Recommended Next Step |")
        lines.append("|---|---|---|---|")
        for row in blocked:
            row = _legacy._dict(row)
            status = row.get("preview_status", "-")
            lines.append(
                f"| {row.get('symbol', '-')} | "
                f"{_legacy._status_icon(status)} `{status}` | "
                f"{row.get('reason', '-')} | "
                f"{row.get('recommended_next_step', '-')} |"
            )
        lines.append("")

    if ticket_status == "ready_for_manual_approval":
        lines.append("### Manual Approval Safety")
        lines.append(
            "Ticket นี้เป็น read-only/manual-approval เท่านั้น "
            "ยังไม่ cancel/replace/submit order จริง "
            "ต้องมีขั้นตอนอนุมัติแยกก่อน execution"
        )
        lines.append("")
    elif ticket_status == "blocked":
        lines.append("### Operator Attention Required")
        lines.append(
            "Ticket นี้ยังมี blocker ต้องแก้ก่อน แล้วจึง refresh order review "
            "preview รอบนี้ยังไม่มีการ cancel/replace/submit order จริง"
        )
        lines.append("")
    elif ticket_status in {"no_action_required", "empty"}:
        lines.append("### No Operator Action Required")
        lines.append(
            "ไม่พบรายการที่ต้องอนุมัติหรือแก้ไขเพิ่มเติมใน Ticket รอบนี้ "
            "และไม่มีการ cancel/replace/submit order จริง"
        )
        lines.append("")


def main() -> int:
    report_path = Path("reports/hourly-auto-trading-report.json")
    if not report_path.exists():
        return _legacy.main()

    raw = json.loads(report_path.read_text(encoding="utf-8"))
    enriched = enrich_hourly_artifact(raw)
    report_path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return _legacy.main()


_legacy.render_curator_signals = render_curator_signals
_legacy.render_order_review_approval_ticket = render_order_review_approval_ticket
_legacy.render_portfolio_section = render_portfolio_section


if __name__ == "__main__":
    raise SystemExit(main())

import pytest

from scripts.protection_reconciliation_client import (
    CONFIRMATION_PHRASE,
    build_execution_payload,
)


def preview_response():
    return {
        "status": "success",
        "data": {
            "ticket": {
                "ticket_id": "protection-reconciliation-abc123",
                "symbols": ["ACGL", "BKNG"],
            }
        },
    }


def proposals():
    return [
        {
            "symbol": "ACGL",
            "qty": 151,
            "stop_price": 95.0,
            "take_profit_price": 116.6,
        }
    ]


def test_build_execution_payload_uses_latest_preview_ticket():
    payload = build_execution_payload(
        preview_response(),
        proposals=proposals(),
        symbols=["ACGL"],
        confirmation_phrase=CONFIRMATION_PHRASE,
        allow_multi_symbol=False,
    )

    assert payload["reconciliation_ticket_id"] == "protection-reconciliation-abc123"
    assert payload["symbols"] == ["ACGL"]
    assert payload["execute_paper"] is True
    assert payload["risk_proposals"] == proposals()


def test_wrong_confirmation_phrase_fails_closed():
    with pytest.raises(ValueError, match="confirmation phrase"):
        build_execution_payload(
            preview_response(),
            proposals=proposals(),
            symbols=["ACGL"],
            confirmation_phrase="WRONG",
            allow_multi_symbol=False,
        )


def test_empty_symbol_selection_fails_closed():
    with pytest.raises(ValueError, match="at least one symbol"):
        build_execution_payload(
            preview_response(),
            proposals=proposals(),
            symbols=[],
            confirmation_phrase=CONFIRMATION_PHRASE,
            allow_multi_symbol=False,
        )


def test_multi_symbol_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="allow-multi-symbol"):
        build_execution_payload(
            preview_response(),
            proposals=proposals(),
            symbols=["ACGL", "BKNG"],
            confirmation_phrase=CONFIRMATION_PHRASE,
            allow_multi_symbol=False,
        )

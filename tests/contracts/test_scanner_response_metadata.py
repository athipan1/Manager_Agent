from app.contracts.scanner import ScannerResponseData


def test_scanner_response_data_preserves_metadata_and_errors():
    response = ScannerResponseData.model_validate(
        {
            "scan_type": "best_fundamentals",
            "count": 1,
            "candidates": [
                {
                    "symbol": "ACGL",
                    "candidate_score": 0.919,
                    "recommendation_hint": "FUNDAMENTAL_TOP_10",
                }
            ],
            "metadata": {
                "scanner_discovery_cache_hit": True,
                "scanner_discovery_cache_one_shot": True,
            },
            "errors": {"BAD": "missing financial statements"},
        }
    )

    assert response.metadata["scanner_discovery_cache_hit"] is True
    assert response.metadata["scanner_discovery_cache_one_shot"] is True
    assert response.errors == {"BAD": "missing financial statements"}
    assert response.candidates[0].symbol == "ACGL"


def test_scanner_response_preserves_native_research_lane_for_shadow():
    research_candidate = {
        "symbol": "MSFT",
        "candidate_score": 0.61,
        "recommendation_hint": "WATCHLIST",
        "metadata": {
            "details": {
                "data_bundle": {
                    "opportunity_profile": {
                        "schema_version": "scanner-opportunity-profile.v1",
                        "status": "review",
                        "opportunity_score": 0.48,
                    }
                }
            }
        },
    }
    response = ScannerResponseData.model_validate(
        {
            "scan_type": "best_fundamentals",
            "count": 0,
            "candidates": [],
            "production_candidates": [],
            "research_candidates": [research_candidate],
            "lane_summary": {
                "research_count": 1,
                "research_execution_mode": "shadow",
            },
        }
    )

    assert response.research_candidates == [research_candidate]
    assert response.lane_summary["research_count"] == 1
    assert len(response.review_candidates) == 1
    shadow_row = response.review_candidates[0]
    assert shadow_row["symbol"] == "MSFT"
    assert shadow_row["decision"] == "REVIEW"
    assert shadow_row["allowed"] is False
    assert shadow_row["reason_code"] == "SCANNER_NATIVE_RESEARCH_SHADOW"
    assert shadow_row["workflow_failure"] is False
    assert shadow_row["research_lane_eligible"] is True
    assert shadow_row["controlled_no_trade"] is True
    assert shadow_row["broker_order_authorized"] is False
    assert shadow_row["risk_approval_allowed"] is False
    assert shadow_row["execution_agent_allowed"] is False
    assert shadow_row["lane_source"] == "scanner_native_research"


def test_repeated_scanner_contract_validation_does_not_duplicate_shadow_rows():
    first = ScannerResponseData.model_validate(
        {
            "scan_type": "best_fundamentals",
            "count": 0,
            "candidates": [],
            "research_candidates": [
                {
                    "symbol": "NVDA",
                    "candidate_score": 0.65,
                    "recommendation_hint": "WATCHLIST",
                }
            ],
        }
    )

    second = ScannerResponseData.model_validate(first.model_dump(mode="json"))

    eligible = [
        row
        for row in second.review_candidates
        if row.get("research_lane_eligible") is True
        and row.get("symbol") == "NVDA"
    ]
    assert len(eligible) == 1

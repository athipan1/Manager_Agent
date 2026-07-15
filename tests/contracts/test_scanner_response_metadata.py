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

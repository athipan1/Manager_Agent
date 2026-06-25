from app.services.scanner_candidate_service import (
    candidate_to_dict,
    scanner_candidate_metadata,
    scanner_candidate_score,
    scanner_candidate_symbol,
)


class Candidate:
    symbol = "AAPL"
    candidate_score = 82
    confidence_score = None
    fundamental_score = None
    technical_score = 0.4
    discovery_rank = 2
    recommendation = "BUY"
    recommendation_hint = "watchlist"
    exchange = "NASDAQ"
    screener = "NASDAQ_SP500"
    tags = ["quality"]
    reasons = ["strong balance sheet"]
    raw_scores = {"quality_score": 0.9}
    metadata = {"source": "unit-test"}


def test_candidate_to_dict_supports_plain_objects():
    data = candidate_to_dict(Candidate())

    assert data["symbol"] == "AAPL"
    assert data["candidate_score"] == 82
    assert data["metadata"] == {"source": "unit-test"}


def test_scanner_candidate_symbol():
    assert scanner_candidate_symbol({"symbol": "MSFT"}) == "MSFT"
    assert scanner_candidate_symbol(Candidate()) == "AAPL"


def test_scanner_candidate_score_prefers_candidate_score():
    assert scanner_candidate_score({"candidate_score": 75}) == 0.75


def test_scanner_candidate_score_uses_raw_scores_when_needed():
    assert scanner_candidate_score({"metadata": {"raw_scores": {"quality_score": 0.67}}}) == 0.67


def test_scanner_candidate_score_falls_back_to_rank():
    assert scanner_candidate_score({"discovery_rank": 3}) == 0.84


def test_scanner_candidate_metadata_combines_top_level_and_metadata():
    metadata = scanner_candidate_metadata(Candidate())

    assert metadata["candidate_score"] == 82
    assert metadata["technical_score"] == 0.4
    assert metadata["exchange"] == "NASDAQ"
    assert metadata["metadata"] == {"source": "unit-test"}

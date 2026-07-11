from app.scanner_policy_router import (
    NEWS_MOMENTUM,
    UNASSIGNED,
    VALUE_REBOUND,
    StrategyBucketClassification,
    _resolve_value_momentum_overlap,
)


def _policy_v3_item():
    return {
        "scanner_candidate": {
            "metadata": {
                "bucket_hint_version": "scanner-bucket-hints-v2",
                "bucket_hint_policy_version": "scanner-bucket-hint-policy-v3",
                "bucket_hint_status": "suggested",
                "primary_strategy_bucket_hint": VALUE_REBOUND,
                "bucket_hint_scores": {
                    VALUE_REBOUND: 0.8578,
                    NEWS_MOMENTUM: 0.54,
                },
                "bucket_hint_dominance_rule": "deep_value_without_income_dominance",
            }
        }
    }


def _conflict(*extra_reasons: str):
    return StrategyBucketClassification(
        bucket=UNASSIGNED,
        confidence=0.76,
        reasons=(
            "conflicting_bucket_evidence",
            "scanner_primary_hint:value_rebound",
            "low_pe_ratio:7.82",
            "valuation_score:0.95",
            "technical_momentum_trend:momentum=0.81,trend=0.80",
            "scanner_policy_v3_consumed",
            "scanner_policy_primary:value_rebound",
            "scanner_dominance_rule:deep_value_without_income_dominance",
            *extra_reasons,
        ),
        status="conflict",
        proposed_bucket=VALUE_REBOUND,
        conflict_buckets=(VALUE_REBOUND, NEWS_MOMENTUM),
        evidence_gate_passed=True,
        evidence_summary={"contract": "manager-analysis-evidence-v1"},
    )


def test_value_policy_resolves_technical_only_momentum_conflict():
    decision = _resolve_value_momentum_overlap(_policy_v3_item(), _conflict())

    assert decision.bucket == VALUE_REBOUND
    assert decision.status == "classified"
    assert decision.proposed_bucket == VALUE_REBOUND
    assert decision.conflict_buckets == ()
    assert decision.allows_new_entry is True
    assert "value_policy_dominates_technical_momentum_only" in decision.reasons


def test_explicit_news_identity_keeps_value_momentum_conflict_quarantined():
    decision = _resolve_value_momentum_overlap(
        _policy_v3_item(),
        _conflict("tag_evidence:news,catalyst"),
    )

    assert decision.bucket == UNASSIGNED
    assert decision.status == "conflict"
    assert set(decision.conflict_buckets) == {VALUE_REBOUND, NEWS_MOMENTUM}

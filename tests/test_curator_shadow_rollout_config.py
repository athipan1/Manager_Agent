from pathlib import Path


def test_curator_compose_enables_shadow_ensemble_in_advisory_mode():
    compose = Path("docker-compose.curator.yml").read_text(encoding="utf-8")

    assert "CURATOR_SHADOW_ENSEMBLE_ENABLED: ${CURATOR_SHADOW_ENSEMBLE_ENABLED:-true}" in compose
    assert "CURATOR_SHADOW_ENSEMBLE_REQUIRED: ${CURATOR_SHADOW_ENSEMBLE_REQUIRED:-false}" in compose
    assert "CURATOR_SHADOW_ENSEMBLE_MIN_AGREEMENT: ${CURATOR_SHADOW_ENSEMBLE_MIN_AGREEMENT:-0.60}" in compose
    assert "CURATOR_SHADOW_ENSEMBLE_MAX_SKILLS: ${CURATOR_SHADOW_ENSEMBLE_MAX_SKILLS:-8}" in compose
    assert "CURATOR_SHADOW_ENSEMBLE_TIMEOUT: ${CURATOR_SHADOW_ENSEMBLE_TIMEOUT:-8.0}" in compose


def test_rollout_document_keeps_risk_gate_and_rollback_explicit():
    document = Path("docs/curator_shadow_ensemble_rollout.md").read_text(encoding="utf-8")

    assert "Risk_Agent remains mandatory" in document
    assert "CURATOR_SHADOW_ENSEMBLE_REQUIRED=true" in document
    assert "CURATOR_SHADOW_ENSEMBLE_REQUIRED=false" in document
    assert "At least 50 ensemble observations" in document

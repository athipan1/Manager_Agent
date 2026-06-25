from pathlib import Path


def test_modular_entrypoint_migration_docs_reference_both_entrypoints():
    doc = Path("docs/modular_entrypoint_migration.md").read_text(encoding="utf-8")

    assert "app.main:app" in doc
    assert "app.main_modular:app" in doc


def test_modular_entrypoint_migration_docs_include_safe_rollout_and_rollback():
    doc = Path("docs/modular_entrypoint_migration.md").read_text(encoding="utf-8")

    assert "Safe rollout plan" in doc
    assert "Rollback" in doc
    assert "No database migration is required" in doc


def test_modular_entrypoint_migration_docs_list_migrated_single_analysis_routes():
    doc = Path("docs/modular_entrypoint_migration.md").read_text(encoding="utf-8")

    assert "POST /analyze" in doc
    assert "POST /dry-run/analyze" in doc
    assert "app/routes/single_analysis.py" in doc
    assert "app/workflows/single_analysis_workflow.py" in doc

from pathlib import Path


DOC_PATH = Path("docs/modular_route_parity_checklist.md")


EXPECTED_ROUTES = [
    "/health",
    "/preflight/live",
    "/analyze",
    "/dry-run/analyze",
    "/analyze-multi",
    "/discover-analyze-trade",
    "/scan-and-analyze",
    "/trade-replay",
]


def test_modular_route_parity_doc_references_both_entrypoints():
    doc = DOC_PATH.read_text(encoding="utf-8")

    assert "app.main:app" in doc
    assert "app.main_modular:app" in doc


def test_modular_route_parity_doc_lists_all_migrated_routes():
    doc = DOC_PATH.read_text(encoding="utf-8")

    for route in EXPECTED_ROUTES:
        assert route in doc


def test_modular_route_parity_doc_includes_validation_and_rollback():
    doc = DOC_PATH.read_text(encoding="utf-8")

    assert "python -m compileall app tests" in doc
    assert "pytest -q tests/test_main_modular.py tests/test_app_factory.py tests/routes tests/workflows tests/services" in doc
    assert "uvicorn app.main:app --host 0.0.0.0 --port 8000" in doc
    assert "uvicorn app.main_modular:app --host 0.0.0.0 --port 8000" in doc

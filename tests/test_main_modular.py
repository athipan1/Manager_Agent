from app.main_modular import app


def test_main_modular_exposes_single_analysis_routes():
    paths = {route.path for route in app.routes}

    assert "/analyze" in paths
    assert "/dry-run/analyze" in paths


def test_main_modular_does_not_duplicate_single_analysis_routes():
    paths = [route.path for route in app.routes if route.path in {"/analyze", "/dry-run/analyze"}]

    assert paths.count("/analyze") == 1
    assert paths.count("/dry-run/analyze") == 1

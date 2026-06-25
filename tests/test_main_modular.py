from app.main_modular import app


MIGRATED_PATHS = {
    "/analyze",
    "/dry-run/analyze",
    "/analyze-multi",
    "/health",
    "/preflight/live",
    "/trade-replay",
}


def test_main_modular_exposes_migrated_routes():
    paths = {route.path for route in app.routes}

    assert "/analyze" in paths
    assert "/dry-run/analyze" in paths
    assert "/analyze-multi" in paths
    assert "/health" in paths
    assert "/preflight/live" in paths
    assert "/trade-replay" in paths


def test_main_modular_does_not_duplicate_migrated_routes():
    paths = [route.path for route in app.routes if route.path in MIGRATED_PATHS]

    assert paths.count("/analyze") == 1
    assert paths.count("/dry-run/analyze") == 1
    assert paths.count("/analyze-multi") == 1
    assert paths.count("/health") == 1
    assert paths.count("/preflight/live") == 1
    assert paths.count("/trade-replay") == 1

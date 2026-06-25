from app.main_modular import app


MIGRATED_PATHS = {
    "/analyze",
    "/dry-run/analyze",
    "/analyze-multi",
    "/discover-analyze-trade",
    "/scan-and-analyze",
    "/health",
    "/preflight/live",
    "/trade-replay",
}


def test_main_modular_exposes_migrated_routes():
    paths = {route.path for route in app.routes}

    for path in MIGRATED_PATHS:
        assert path in paths


def test_main_modular_does_not_duplicate_migrated_routes():
    paths = [route.path for route in app.routes if route.path in MIGRATED_PATHS]

    for path in MIGRATED_PATHS:
        assert paths.count(path) == 1

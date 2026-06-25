from app.app_factory import create_app


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


def route_methods(app):
    return {route.path: route.methods for route in app.routes if hasattr(route, "methods")}


def test_create_app_registers_modular_routes_by_default():
    methods = route_methods(create_app())

    for path in MIGRATED_PATHS:
        assert path in methods
    assert "POST" in methods["/scan-and-analyze"]


def test_create_app_can_skip_scanner_routes():
    methods = route_methods(create_app(include_scanner=False))

    assert "/scan-and-analyze" not in methods
    assert "/analyze" in methods
    assert "/analyze-multi" in methods
    assert "/discover-analyze-trade" in methods


def test_create_app_does_not_duplicate_registered_paths():
    paths = [route.path for route in create_app().routes if route.path in MIGRATED_PATHS]

    for path in MIGRATED_PATHS:
        assert paths.count(path) == 1

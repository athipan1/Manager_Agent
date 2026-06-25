from app.app_factory import create_app


def route_methods(app):
    return {
        route.path: route.methods
        for route in app.routes
        if hasattr(route, "methods")
    }


def test_create_app_registers_single_analysis_routes_by_default():
    app = create_app()

    methods = route_methods(app)
    assert "/analyze" in methods
    assert "/dry-run/analyze" in methods
    assert "POST" in methods["/analyze"]
    assert "POST" in methods["/dry-run/analyze"]


def test_create_app_registers_multi_analysis_routes_by_default():
    app = create_app()

    methods = route_methods(app)
    assert "/analyze-multi" in methods
    assert "POST" in methods["/analyze-multi"]


def test_create_app_registers_discovery_routes_by_default():
    app = create_app()

    methods = route_methods(app)
    assert "/discover-analyze-trade" in methods
    assert "POST" in methods["/discover-analyze-trade"]


def test_create_app_registers_system_routes_by_default():
    app = create_app()

    methods = route_methods(app)
    assert "/health" in methods
    assert "/preflight/live" in methods
    assert "GET" in methods["/health"]
    assert "GET" in methods["/preflight/live"]


def test_create_app_registers_trade_replay_routes_by_default():
    app = create_app()

    methods = route_methods(app)
    assert "/trade-replay" in methods
    assert "POST" in methods["/trade-replay"]


def test_create_app_can_skip_single_analysis_routes():
    app = create_app(include_single_analysis=False)

    methods = route_methods(app)
    assert "/analyze" not in methods
    assert "/dry-run/analyze" not in methods
    assert "/analyze-multi" in methods
    assert "/discover-analyze-trade" in methods
    assert "/health" in methods
    assert "/preflight/live" in methods
    assert "/trade-replay" in methods


def test_create_app_can_skip_multi_analysis_routes():
    app = create_app(include_multi_analysis=False)

    methods = route_methods(app)
    assert "/analyze-multi" not in methods
    assert "/analyze" in methods
    assert "/dry-run/analyze" in methods
    assert "/discover-analyze-trade" in methods
    assert "/health" in methods
    assert "/preflight/live" in methods
    assert "/trade-replay" in methods


def test_create_app_can_skip_discovery_routes():
    app = create_app(include_discovery=False)

    methods = route_methods(app)
    assert "/discover-analyze-trade" not in methods
    assert "/analyze" in methods
    assert "/dry-run/analyze" in methods
    assert "/analyze-multi" in methods
    assert "/health" in methods
    assert "/preflight/live" in methods
    assert "/trade-replay" in methods


def test_create_app_can_skip_system_routes():
    app = create_app(include_system=False)

    methods = route_methods(app)
    assert "/health" not in methods
    assert "/preflight/live" not in methods
    assert "/analyze" in methods
    assert "/dry-run/analyze" in methods
    assert "/analyze-multi" in methods
    assert "/discover-analyze-trade" in methods
    assert "/trade-replay" in methods


def test_create_app_can_skip_trade_replay_routes():
    app = create_app(include_trade_replay=False)

    methods = route_methods(app)
    assert "/trade-replay" not in methods
    assert "/analyze" in methods
    assert "/dry-run/analyze" in methods
    assert "/analyze-multi" in methods
    assert "/discover-analyze-trade" in methods
    assert "/health" in methods
    assert "/preflight/live" in methods


def test_create_app_does_not_duplicate_registered_paths():
    app = create_app()

    paths = [
        route.path
        for route in app.routes
        if route.path in {
            "/analyze",
            "/dry-run/analyze",
            "/analyze-multi",
            "/discover-analyze-trade",
            "/health",
            "/preflight/live",
            "/trade-replay",
        }
    ]
    assert paths.count("/analyze") == 1
    assert paths.count("/dry-run/analyze") == 1
    assert paths.count("/analyze-multi") == 1
    assert paths.count("/discover-analyze-trade") == 1
    assert paths.count("/health") == 1
    assert paths.count("/preflight/live") == 1
    assert paths.count("/trade-replay") == 1

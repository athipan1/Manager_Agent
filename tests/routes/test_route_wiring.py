from fastapi import FastAPI
from fastapi.routing import iter_route_contexts

from app.routes.wiring import register_single_analysis_routes


def test_register_single_analysis_routes_adds_expected_paths():
    app = FastAPI()

    register_single_analysis_routes(app)

    paths = {route.path for route in iter_route_contexts(app.routes)}
    assert "/analyze" in paths
    assert "/dry-run/analyze" in paths


def test_register_single_analysis_routes_adds_post_methods():
    app = FastAPI()

    register_single_analysis_routes(app)

    methods_by_path = {
        route.path: route.methods
        for route in iter_route_contexts(app.routes)
        if route.path in {"/analyze", "/dry-run/analyze"}
    }
    assert "POST" in methods_by_path["/analyze"]
    assert "POST" in methods_by_path["/dry-run/analyze"]

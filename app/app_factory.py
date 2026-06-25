"""FastAPI application factory for Manager_Agent.

This module is the migration bridge from the legacy monolithic `app.main` file
to modular route registration. It lets tests and future entrypoints create a
FastAPI app with selected routers without importing every legacy route.
"""

from __future__ import annotations

from fastapi import FastAPI

from .routes.wiring import register_single_analysis_routes


def create_app(*, include_single_analysis: bool = True) -> FastAPI:
    """Create a Manager_Agent FastAPI application.

    Args:
        include_single_analysis: Register `/analyze` and `/dry-run/analyze`
            routes backed by `single_analysis_workflow`.
    """
    app = FastAPI()

    if include_single_analysis:
        register_single_analysis_routes(app)

    return app

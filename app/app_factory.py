"""FastAPI application factory for Manager_Agent.

This module is the migration bridge from the legacy monolithic `app.main` file
to modular route registration. It lets tests and future entrypoints create a
FastAPI app with selected routers without importing every legacy route.
"""

from __future__ import annotations

from fastapi import FastAPI

from .routes.wiring import (
    register_multi_analysis_routes,
    register_single_analysis_routes,
    register_system_routes,
    register_trade_replay_routes,
)


def create_app(
    *,
    include_single_analysis: bool = True,
    include_multi_analysis: bool = True,
    include_system: bool = True,
    include_trade_replay: bool = True,
) -> FastAPI:
    """Create a Manager_Agent FastAPI application.

    Args:
        include_single_analysis: Register `/analyze` and `/dry-run/analyze`
            routes backed by `single_analysis_workflow`.
        include_multi_analysis: Register `/analyze-multi`.
        include_system: Register operational routes such as `/health` and
            `/preflight/live`.
        include_trade_replay: Register `/trade-replay`.
    """
    app = FastAPI()

    if include_system:
        register_system_routes(app)

    if include_single_analysis:
        register_single_analysis_routes(app)

    if include_multi_analysis:
        register_multi_analysis_routes(app)

    if include_trade_replay:
        register_trade_replay_routes(app)

    return app

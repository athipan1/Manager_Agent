from __future__ import annotations

from fastapi import FastAPI

from .dashboard_security import configure_dashboard_cors
from .routes.web_control import router as web_control_router
from .routes.web_finance import router as web_finance_router
from .routes.wiring import (
    register_alpha_agent_routes,
    register_discovery_routes,
    register_multi_analysis_routes,
    register_scanner_routes,
    register_single_analysis_routes,
    register_system_routes,
    register_trade_replay_routes,
)


def create_app(
    *,
    include_single_analysis: bool = True,
    include_multi_analysis: bool = True,
    include_discovery: bool = True,
    include_scanner: bool = True,
    include_system: bool = True,
    include_trade_replay: bool = True,
    include_alpha_agents: bool = True,
    include_web_control: bool = True,
) -> FastAPI:
    app = FastAPI()
    configure_dashboard_cors(app)

    if include_system:
        register_system_routes(app)

    if include_single_analysis:
        register_single_analysis_routes(app)

    if include_multi_analysis:
        register_multi_analysis_routes(app)

    if include_discovery:
        register_discovery_routes(app)

    if include_scanner:
        register_scanner_routes(app)

    if include_trade_replay:
        register_trade_replay_routes(app)

    if include_alpha_agents:
        register_alpha_agent_routes(app)

    if include_web_control:
        app.include_router(web_control_router)
        app.include_router(web_finance_router)

    return app

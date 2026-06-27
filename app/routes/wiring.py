from __future__ import annotations

from fastapi import FastAPI

from .alpha_agents import router as alpha_agents_router
from .discovery import router as discovery_router
from .multi_analysis import router as multi_analysis_router
from .scanner import router as scanner_router
from .single_analysis import router as single_analysis_router
from .system import router as system_router
from .trade_replay import router as trade_replay_router


def register_single_analysis_routes(app: FastAPI) -> None:
    app.include_router(single_analysis_router)


def register_multi_analysis_routes(app: FastAPI) -> None:
    app.include_router(multi_analysis_router)


def register_discovery_routes(app: FastAPI) -> None:
    app.include_router(discovery_router)


def register_scanner_routes(app: FastAPI) -> None:
    app.include_router(scanner_router)


def register_system_routes(app: FastAPI) -> None:
    app.include_router(system_router)


def register_trade_replay_routes(app: FastAPI) -> None:
    app.include_router(trade_replay_router)


def register_alpha_agent_routes(app: FastAPI) -> None:
    app.include_router(alpha_agents_router)

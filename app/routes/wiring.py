"""Route registration helpers for Manager_Agent.

Keeping route registration in a small module lets `app.main` migrate from
inline route declarations to modular routers one router at a time.
"""

from __future__ import annotations

from fastapi import FastAPI

from .discovery import router as discovery_router
from .multi_analysis import router as multi_analysis_router
from .single_analysis import router as single_analysis_router
from .system import router as system_router
from .trade_replay import router as trade_replay_router


def register_single_analysis_routes(app: FastAPI) -> None:
    """Register the single-symbol analysis router on a FastAPI app."""
    app.include_router(single_analysis_router)


def register_multi_analysis_routes(app: FastAPI) -> None:
    """Register the multi-symbol analysis router on a FastAPI app."""
    app.include_router(multi_analysis_router)


def register_discovery_routes(app: FastAPI) -> None:
    """Register discovery/analyze/trade routes on a FastAPI app."""
    app.include_router(discovery_router)


def register_system_routes(app: FastAPI) -> None:
    """Register system and operational routes on a FastAPI app."""
    app.include_router(system_router)


def register_trade_replay_routes(app: FastAPI) -> None:
    """Register trade replay routes on a FastAPI app."""
    app.include_router(trade_replay_router)

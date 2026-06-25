"""Modular ASGI entrypoint for Manager_Agent.

This entrypoint is intentionally separate from `app.main` while the legacy
monolithic module is being migrated. It creates the FastAPI app through the
modular app factory and only registers routes that have been moved into router
modules.

Run locally with:

    uvicorn app.main_modular:app --reload
"""

from __future__ import annotations

from .app_factory import create_app

app = create_app()

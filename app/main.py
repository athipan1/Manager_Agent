"""Legacy ASGI compatibility shim for Manager_Agent.

The production and local runtime now use ``app.main_modular:app``.  This module
is kept so older imports such as ``from app.main import app`` continue to work
while the codebase finishes migrating fully to modular route/workflow modules.
"""

from __future__ import annotations

from .main_modular import app

__all__ = ["app"]

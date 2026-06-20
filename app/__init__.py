"""Application package bootstrap helpers."""

import fastapi as _fastapi

_OriginalFastAPI = _fastapi.FastAPI


class ManagerFastAPI(_OriginalFastAPI):
    """FastAPI subclass that mounts Manager operational alert routes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .alert_routes import router as alert_router
        self.include_router(alert_router)


_fastapi.FastAPI = ManagerFastAPI

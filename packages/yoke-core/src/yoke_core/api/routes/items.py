"""Item routes — aggregator shim.

The eight item-route handlers live in responsibility-named sibling modules
under ``runtime/api/routes/items_*.py``.  Each sibling exposes its own
``APIRouter`` with the same paths and methods that originally lived in this
file.  This shim aggregates them into a single ``router`` so existing
``app_factory`` registration (``from yoke_core.api.routes.items import router``)
keeps working unchanged.
"""

from __future__ import annotations

from fastapi.routing import APIRouter

from yoke_core.api.routes.items_approve import router as _approve_router
from yoke_core.api.routes.items_board import router as _board_router
from yoke_core.api.routes.items_capability import router as _capability_router
from yoke_core.api.routes.items_health import router as _health_router
from yoke_core.api.routes.items_read import router as _read_router
from yoke_core.api.routes.items_write import router as _write_router

router = APIRouter()
router.include_router(_health_router)
router.include_router(_read_router)
router.include_router(_write_router)
router.include_router(_approve_router)
router.include_router(_capability_router)
router.include_router(_board_router)


__all__ = ["router"]

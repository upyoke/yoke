"""Aggregate item read, write, approval, capability and board routes."""

from __future__ import annotations

from fastapi.routing import APIRouter

from yoke_core.api.routes.items_approve import router as _approve_router
from yoke_core.api.routes.items_board import router as _board_router
from yoke_core.api.routes.items_capability import router as _capability_router
from yoke_core.api.routes.items_read import router as _read_router
from yoke_core.api.routes.items_write import router as _write_router

router = APIRouter()
router.include_router(_read_router)
router.include_router(_write_router)
router.include_router(_approve_router)
router.include_router(_capability_router)
router.include_router(_board_router)


__all__ = ["router"]

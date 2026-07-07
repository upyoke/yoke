"""Session route aggregator — composes lifecycle, claims, inventory, and offer sub-routers.

Imports the four responsibility-named sub-routers and exposes a single ``router``
that ``yoke_core.api.app_factory`` (or ``yoke_core.api.main``) includes. Tests that
need to assert specific request models can import them from their owning
sub-router; this shim re-exports the most common ones for convenience.
"""

from __future__ import annotations

from fastapi.routing import APIRouter

from yoke_core.api.routes.sessions_claims import (
    ClaimWorkRequest,
    HandoffClaimRequest,
    ReleaseClaimRequest,
    router as _claims_router,
)
from yoke_core.api.routes.sessions_inventory import router as _inventory_router
from yoke_core.api.routes.sessions_lifecycle import (
    RegisterSessionRequest,
    router as _lifecycle_router,
)
from yoke_core.api.routes.sessions_offer import (
    SessionOfferRequest,
    router as _offer_router,
)


router = APIRouter()
router.include_router(_lifecycle_router)
router.include_router(_claims_router)
router.include_router(_inventory_router)
router.include_router(_offer_router)


__all__ = [
    "router",
    "ClaimWorkRequest",
    "HandoffClaimRequest",
    "ReleaseClaimRequest",
    "RegisterSessionRequest",
    "SessionOfferRequest",
]

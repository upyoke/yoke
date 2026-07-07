"""System endpoints: status, admin operations."""

import sys
import os

from fastapi import APIRouter, Depends, HTTPException

# Ensure app/ is on sys.path so db/ can be imported
APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from api.dependencies import get_current_user

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    """Return system status (authenticated users only)."""
    return {
        "status": "ok",
        "data": {
            "message": "System operational",
        },
    }

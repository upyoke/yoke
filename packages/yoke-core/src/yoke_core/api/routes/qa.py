"""QA/testing route handlers — extracted from main.py.

Currently empty: QA validation logic is embedded in item update gates
(via GateContext in routes/items.py), not exposed as standalone routes.
This module exists as a placeholder for future QA-specific endpoints.
"""

from __future__ import annotations

from fastapi.routing import APIRouter

router = APIRouter()

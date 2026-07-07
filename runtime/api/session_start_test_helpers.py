"""Shared scaffolding for ``test_session_start*`` modules.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports the constants and ``make_*`` builders defined here and then
declares its own classes verbatim. Keeping shared scaffolding in this module
(instead of in conftest.py) keeps the splits self-contained and lets future
moves stay localized — a sibling AC explicitly forbids new conftest fixtures.
"""

from __future__ import annotations

import os
import sys
from runtime.api.test_constants import TEST_MODEL_ID

# Ensure the repo root is importable for split modules that load this helper.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session import SessionOffer


# Synthetic test item ID — not a real backlog item reference.
TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def test_item_ref(item_id: int) -> str:
    """Build synthetic display IDs without embedding drifting ticket literals."""
    return f"YOK-{item_id}"


def make_offer(**overrides) -> SessionOffer:
    """Build a SessionOffer with sensible defaults for decision-engine tests."""
    defaults = {
        "session_id": "test-session-001",
        "executor": "DARIUS",
        "provider": "anthropic",
        "model": TEST_MODEL_ID,
        "workspace": "/tmp/yoke",
    }
    defaults.update(overrides)
    return SessionOffer(**defaults)


__all__ = [
    "TEST_ITEM_ID",
    "TEST_ITEM_REF",
    "test_item_ref",
    "make_offer",
]

"""Tests for yoke_core.domain.session — import hygiene + supported_paths field.

Sibling of test_session.py: covers domain-import smoke checks and the
SessionOffer.supported_paths field shape (defaults, round-trip, event
context). Do-loop contract assertions and decision priority ordering
remain in test_session.py.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from runtime.api.test_constants import TEST_MODEL_ID

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session import (
    SessionOffer,
    SESSION_OFFERED_EVENT,
)


def _make_offer(**overrides):
    """Helper to create a SessionOffer with sensible defaults."""
    defaults = {
        "session_id": "test-session-001",
        "executor": "DARIUS",
        "provider": "anthropic",
        "model": TEST_MODEL_ID,
        "workspace": "/tmp/yoke",
    }
    defaults.update(overrides)
    return SessionOffer(**defaults)


# ---------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------


class TestImportHygiene:
    """Existing domain imports must continue to work after adding session module."""

    def test_lifecycle_importable(self):
        from yoke_core.domain import lifecycle
        assert hasattr(lifecycle, "ItemStatus")

    def test_approval_importable(self):
        from yoke_core.domain import approval
        assert hasattr(approval, "ApprovalResolution")

    def test_mutations_importable(self):
        from yoke_core.domain import mutations
        assert hasattr(mutations, "ItemState")

    def test_runs_importable(self):
        from yoke_core.domain import runs
        assert hasattr(runs, "DeploymentRun")

    def test_queries_importable(self):
        from yoke_core.domain import queries
        assert hasattr(queries, "ItemFilter")

    def test_board_importable(self):
        from yoke_core.domain import board
        assert hasattr(board, "project_board")

    def test_session_importable(self):
        from yoke_core.domain import session
        assert hasattr(session, "SessionOffer")
        assert hasattr(session, "NextAction")
        assert hasattr(session, "ActionKind")

    def test_decision_engine_importable(self):
        from yoke_core.domain import session
        assert hasattr(session, "decide_next_action")
        assert hasattr(session, "FrontierState")
        assert hasattr(session, "ClaimedWork")
        assert hasattr(session, "NextActionKind")


# ---------------------------------------------------------------------------
# supported_paths field tests
# ---------------------------------------------------------------------------


class TestSessionOfferSupportedPaths:
    """AC-1: SessionOffer has supported_paths field defaulting to empty list.
    Backward compatible when empty."""

    def test_supported_paths_defaults_to_empty_list(self):
        offer = SessionOffer(
            session_id="s1",
            executor="DARIUS",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace="/tmp/work",
        )
        assert offer.supported_paths == []

    def test_supported_paths_accepts_values(self):
        offer = SessionOffer(
            session_id="s1",
            executor="DARIUS",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace="/tmp/work",
            supported_paths=["shepherd", "advance"],
        )
        assert offer.supported_paths == ["shepherd", "advance"]

    def test_supported_paths_round_trip(self):
        offer = _make_offer(supported_paths=["conduct", "usher"])
        as_dict = offer.model_dump()
        restored = SessionOffer(**as_dict)
        assert restored.supported_paths == ["conduct", "usher"]

    def test_supported_paths_in_json_round_trip(self):
        offer = _make_offer(supported_paths=["shepherd"])
        as_json = offer.model_dump_json()
        parsed = json.loads(as_json)
        assert parsed["supported_paths"] == ["shepherd"]

    def test_supported_paths_in_event_shape(self):
        """AC-8: HarnessSessionOffered event context includes supported_paths."""
        assert "supported_paths" in SESSION_OFFERED_EVENT["minimum_context_fields"]

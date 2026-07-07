"""SessionOffer, FrontierState, ClaimedWork primitives."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.session import (
    ClaimedWork,
    FrontierState,
    SessionOffer,
)
from runtime.api.session_start_test_helpers import TEST_ITEM_REF
from runtime.api.test_constants import TEST_MODEL_ID


# ---------------------------------------------------------------------------
# SessionOffer tests
# ---------------------------------------------------------------------------


class TestSessionOffer:
    """Construction, validation, and serialization of SessionOffer."""

    def _make_offer(self, **overrides):
        defaults = {
            "session_id": "sess-abc-123",
            "executor": "DARIUS",
            "provider": "anthropic",
            "model": TEST_MODEL_ID,
            "capabilities": ["browser", "shell", "file_write"],
            "workspace": "/Users/bee/yoke",
            "execution_lane": "primary",
            "offered_at": "2026-03-31T12:00:00Z",
        }
        defaults.update(overrides)
        return SessionOffer(**defaults)

    def test_construction_with_all_fields(self):
        offer = self._make_offer()
        assert offer.session_id == "sess-abc-123"
        assert offer.executor == "DARIUS"
        assert offer.provider == "anthropic"
        assert offer.model == TEST_MODEL_ID
        assert offer.capabilities == ["browser", "shell", "file_write"]
        assert offer.workspace == "/Users/bee/yoke"
        assert offer.execution_lane == "primary"
        assert offer.offered_at == "2026-03-31T12:00:00Z"

    def test_execution_lane_defaults_to_primary(self):
        offer = SessionOffer(
            session_id="s1",
            executor="ALTMAN",
            provider="openai",
            model="gpt-4",
            workspace="/tmp/work",
        )
        assert offer.execution_lane == "primary"

    def test_capabilities_defaults_to_empty_list(self):
        offer = SessionOffer(
            session_id="s1",
            executor="DARIUS",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace="/tmp/work",
        )
        assert offer.capabilities == []

    def test_offered_at_auto_populated(self):
        offer = SessionOffer(
            session_id="s1",
            executor="DARIUS",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace="/tmp/work",
        )
        assert offer.offered_at is not None
        assert "T" in offer.offered_at
        assert offer.offered_at.endswith("Z")

    def test_serialization_round_trip(self):
        offer = self._make_offer()
        as_dict = offer.model_dump()
        restored = SessionOffer(**as_dict)
        assert restored == offer

    def test_json_round_trip(self):
        offer = self._make_offer()
        as_json = offer.model_dump_json()
        parsed = json.loads(as_json)
        restored = SessionOffer(**parsed)
        assert restored == offer

    def test_required_fields_enforced(self):
        with pytest.raises(Exception):
            SessionOffer()  # Missing required fields

    def test_session_id_required(self):
        with pytest.raises(Exception):
            SessionOffer(
                executor="DARIUS",
                provider="anthropic",
                model=TEST_MODEL_ID,
                workspace="/tmp/work",
            )

    def test_identity_fields_present_for_correlation(self):
        """AC-6: session_id unique+stable, execution_lane present."""
        offer = self._make_offer()
        # These fields must exist and be non-empty for claim/lease correlation
        assert offer.session_id
        assert offer.executor
        assert offer.execution_lane

    def test_executor_stays_harness_identity_while_lane_carries_routing(self):
        """T7 AC-4: executor carries harness identity (claude-code),
        execution_lane carries delivery-family lane (DARIUS/ALTMAN)."""
        offer = SessionOffer(
            session_id="sess-ac4",
            executor="claude-code",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace="/tmp/work",
            execution_lane="DARIUS",
        )
        # executor is the harness identity, NOT the lane.
        # AC-11 exception: this test pins the coarse `claude-code`
        # family value to verify SessionOffer round-trips it verbatim.
        assert offer.executor == "claude-code"
        # execution_lane carries the delivery-family lane
        assert offer.execution_lane == "DARIUS"

    def test_executor_and_lane_are_independent_fields(self):
        """T7 AC-4: changing lane does not affect executor."""
        for lane in ("DARIUS", "ALTMAN", "primary"):
            offer = SessionOffer(
                session_id=f"sess-{lane}",
                executor="codex",
                provider="openai",
                model="o3-mini",
                workspace="/tmp/work",
                execution_lane=lane,
            )
            # AC-11 exception: this test pins the coarse `codex`
            # family value to verify SessionOffer round-trips it verbatim.
            assert offer.executor == "codex"
            assert offer.execution_lane == lane

    def test_supported_paths_advertises_refine_polish(self):
        """T7: supported_paths can include refine and polish."""
        offer = SessionOffer(
            session_id="sess-rp",
            executor="claude-code",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace="/tmp/work",
            supported_paths=["refine", "polish", "shepherd", "conduct", "advance", "usher"],
        )
        assert "refine" in offer.supported_paths
        assert "polish" in offer.supported_paths
        assert len(offer.supported_paths) == 6


# ---------------------------------------------------------------------------
# FrontierState
# ---------------------------------------------------------------------------


class TestFrontierState:
    """AC-3: FrontierState captures runnable_items, blocked_items, sml_coherent, drift_review."""

    def test_default_construction(self):
        fs = FrontierState()
        assert fs.runnable_items == []
        assert fs.blocked_items == []
        assert fs.sml_coherent is True
        assert fs.drift_review is None

    def test_custom_construction(self):
        fs = FrontierState(
            runnable_items=["YOK-10", "YOK-11"],
            blocked_items=["YOK-12"],
            sml_coherent=False,
            drift_review={"classification": "sml_only", "summary": "test", "checkpoint_start": "", "reviewed_through": "", "delivered_items": []},
        )
        assert fs.runnable_items == ["YOK-10", "YOK-11"]
        assert fs.blocked_items == ["YOK-12"]
        assert fs.sml_coherent is False
        assert fs.drift_review["classification"] == "sml_only"

    def test_frozen(self):
        fs = FrontierState(runnable_items=["YOK-1"])
        with pytest.raises(AttributeError):
            fs.sml_coherent = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ClaimedWork
# ---------------------------------------------------------------------------


class TestClaimedWork:
    """ClaimedWork dataclass for active claims input."""

    def test_default_construction(self):
        cw = ClaimedWork()
        assert cw.item_id is None
        assert cw.epic_id is None
        assert cw.task_num is None
        assert cw.status is None

    def test_item_claim(self):
        cw = ClaimedWork(item_id=TEST_ITEM_REF, status="active")
        assert cw.item_id == TEST_ITEM_REF
        assert cw.status == "active"

    def test_epic_task_claim(self):
        # epic task status uses implementing, not legacy active
        cw = ClaimedWork(epic_id=100, task_num=3, status="implementing")
        assert cw.epic_id == 100
        assert cw.task_num == 3

    def test_frozen(self):
        cw = ClaimedWork(item_id="YOK-1")
        with pytest.raises(AttributeError):
            cw.item_id = "YOK-2"  # type: ignore[misc]

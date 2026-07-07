"""NextAction construction, kind alias, and chainable field tests."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.session import (
    ActionKind,
    NextAction,
)
from runtime.api.session_start_test_helpers import TEST_ITEM_REF


# ---------------------------------------------------------------------------
# NextAction tests
# ---------------------------------------------------------------------------


class TestNextAction:
    """Construction, validation, and serialization of NextAction."""

    def _make_action(self, **overrides):
        defaults = {
            "action": "charge",
            "reason": "Backlog has ready items; session is idle.",
            "correlation_id": "sess-abc-123",
            "context": {"item_id": TEST_ITEM_REF, "title": "Implement feature X"},
        }
        defaults.update(overrides)
        return NextAction(**defaults)

    def test_construction_with_all_fields(self):
        na = self._make_action()
        assert na.action == ActionKind.CHARGE
        assert na.reason == "Backlog has ready items; session is idle."
        assert na.correlation_id == "sess-abc-123"
        assert na.context == {"item_id": TEST_ITEM_REF, "title": "Implement feature X"}

    def test_context_defaults_to_none(self):
        na = NextAction(
            action="wait",
            reason="No work available.",
            correlation_id="s1",
        )
        assert na.context is None

    def test_all_six_action_kinds(self):
        """AC-2: All six canonical values must be representable."""
        for kind in ("resume", "charge", "feed", "strategize", "wait", "escalate"):
            na = NextAction(
                action=kind,
                reason=f"Testing {kind}",
                correlation_id="s1",
            )
            assert na.action.value == kind

    def test_invalid_action_rejected(self):
        with pytest.raises(Exception):
            NextAction(
                action="invalid_action",
                reason="Should fail.",
                correlation_id="s1",
            )

    def test_serialization_round_trip(self):
        na = self._make_action()
        as_dict = na.model_dump()
        restored = NextAction(**as_dict)
        assert restored == na

    def test_json_round_trip(self):
        na = self._make_action()
        as_json = na.model_dump_json()
        parsed = json.loads(as_json)
        restored = NextAction(**parsed)
        assert restored == na

    def test_required_fields_enforced(self):
        with pytest.raises(Exception):
            NextAction()

    def test_context_with_resume_payload(self):
        na = NextAction(
            action="resume",
            reason="Session has active work in progress.",
            correlation_id="s1",
            context={
                "item_id": "YOK-100",
                "worktree": "/tmp/.worktrees/YOK-100",
                "branch": "YOK-100",
            },
        )
        assert na.context["item_id"] == "YOK-100"

    def test_context_with_wait_payload(self):
        na = NextAction(
            action="wait",
            reason="All lanes occupied.",
            correlation_id="s1",
            context={"wait_seconds": 300, "retry_hint": "re-offer after cooldown"},
        )
        assert na.context["wait_seconds"] == 300

    def test_context_with_escalate_payload(self):
        na = NextAction(
            action="escalate",
            reason="Blocked item needs human decision.",
            correlation_id="s1",
            context={
                "item_id": "YOK-55",
                "escalation_type": "human",
                "message": "Dependency approval required.",
            },
        )
        assert na.context["escalation_type"] == "human"


# ---------------------------------------------------------------------------
# NextAction chainable field
# ---------------------------------------------------------------------------


class TestNextActionKindAlias:
    """AC-2: NextAction has a 'kind' property that aliases 'action'."""

    def test_kind_matches_action(self):
        na = NextAction(
            action="charge",
            reason="test",
            correlation_id="s1",
        )
        assert na.kind == na.action
        assert na.kind == ActionKind.CHARGE

    def test_kind_works_for_all_action_kinds(self):
        for ak in ActionKind:
            na = NextAction(
                action=ak,
                reason=f"testing {ak.value}",
                correlation_id="s1",
            )
            assert na.kind == ak


class TestNextActionChainable:
    """AC-2: NextAction has chainable field.  AC-5: chainable semantics."""

    def test_chainable_defaults_to_false(self):
        na = NextAction(
            action="wait",
            reason="idle",
            correlation_id="s1",
        )
        assert na.chainable is False

    def test_chainable_explicit_true(self):
        na = NextAction(
            action="resume",
            reason="resuming work",
            correlation_id="s1",
            chainable=True,
        )
        assert na.chainable is True

    def test_chainable_in_serialization(self):
        na = NextAction(
            action="charge",
            reason="frontier work",
            correlation_id="s1",
            chainable=True,
        )
        d = na.model_dump()
        assert "chainable" in d
        assert d["chainable"] is True
        restored = NextAction(**d)
        assert restored.chainable is True

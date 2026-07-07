"""ActionKind, NextActionKind alias, and event-shape constants."""

from __future__ import annotations

from yoke_core.domain.session import (
    ActionKind,
    NextActionKind,
    NEXT_ACTION_CHOSEN_EVENT,
    SESSION_OFFERED_EVENT,
)


# ---------------------------------------------------------------------------
# ActionKind enum tests
# ---------------------------------------------------------------------------


class TestActionKind:
    """ActionKind enum behavior."""

    def test_enum_values(self):
        assert set(ActionKind) == {
            ActionKind.RESUME,
            ActionKind.CHARGE,
            ActionKind.FEED,
            ActionKind.STRATEGIZE,
            ActionKind.WAIT,
            ActionKind.ESCALATE,
        }

    def test_string_coercion(self):
        assert ActionKind.RESUME == "resume"
        assert ActionKind.CHARGE == "charge"

    def test_enum_count(self):
        assert len(ActionKind) == 6


# ---------------------------------------------------------------------------
# Event shape constant tests
# ---------------------------------------------------------------------------


class TestEventShapes:
    """AC-3: Event shapes conform to event contract conventions."""

    def test_session_offered_shape(self):
        assert SESSION_OFFERED_EVENT["event_name"] == "HarnessSessionOffered"
        assert SESSION_OFFERED_EVENT["event_kind"] == "system"
        assert SESSION_OFFERED_EVENT["event_type"] == "session_offer"
        assert "session_id" in SESSION_OFFERED_EVENT["minimum_context_fields"]
        assert "executor" in SESSION_OFFERED_EVENT["minimum_context_fields"]

    def test_next_action_chosen_shape(self):
        assert NEXT_ACTION_CHOSEN_EVENT["event_name"] == "NextActionChosen"
        assert NEXT_ACTION_CHOSEN_EVENT["event_kind"] == "workflow"
        assert NEXT_ACTION_CHOSEN_EVENT["event_type"] == "session_directive"
        assert "session_id" in NEXT_ACTION_CHOSEN_EVENT["minimum_context_fields"]
        assert "action" in NEXT_ACTION_CHOSEN_EVENT["minimum_context_fields"]

    def test_event_name_pascal_case(self):
        for evt in (SESSION_OFFERED_EVENT, NEXT_ACTION_CHOSEN_EVENT):
            name = evt["event_name"]
            assert name[0].isupper(), f"{name} must start with uppercase"
            assert "_" not in name, f"{name} must be PascalCase, not snake_case"

    def test_event_type_snake_case(self):
        for evt in (SESSION_OFFERED_EVENT, NEXT_ACTION_CHOSEN_EVENT):
            etype = evt["event_type"]
            assert etype == etype.lower(), f"{etype} must be snake_case"

    def test_event_kind_valid(self):
        valid_kinds = {"analytics", "system", "audit", "security", "metric", "lifecycle", "workflow"}
        for evt in (SESSION_OFFERED_EVENT, NEXT_ACTION_CHOSEN_EVENT):
            assert evt["event_kind"] in valid_kinds


# ---------------------------------------------------------------------------
# NextActionKind alias
# ---------------------------------------------------------------------------


class TestNextActionKind:
    """AC-1: NextActionKind enum defines all six modes."""

    def test_alias_is_action_kind(self):
        assert NextActionKind is ActionKind

    def test_six_members(self):
        assert len(NextActionKind) == 6

    def test_all_modes_present(self):
        expected = {"resume", "charge", "feed", "strategize", "wait", "escalate"}
        actual = {m.value for m in NextActionKind}
        assert actual == expected

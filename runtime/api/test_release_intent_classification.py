"""Tests for ``release_intent_classification``."""

from __future__ import annotations

from yoke_core.domain.release_intent_classification import (
    NON_TERMINAL_RELEASE_INTENTS,
    TERMINAL_RELEASE_INTENTS,
    classify_release_intent,
    is_non_terminal_release_intent,
)


def test_non_terminal_set_contains_readiness_check_blocked():
    assert "readiness-check-blocked" in NON_TERMINAL_RELEASE_INTENTS
    assert isinstance(NON_TERMINAL_RELEASE_INTENTS, frozenset)


def test_terminal_set_includes_schema_map_and_two_extras():
    expected_terminal = {
        "handoff-to-polish", "handoff-to-usher", "handed_off", "handoff",
        "finalize-exit", "offer-override", "released", "completed",
        "reclaimed", "expired", "session_ended",
        "idea-complete", "operator-override",
    }
    assert expected_terminal.issubset(TERMINAL_RELEASE_INTENTS)
    assert isinstance(TERMINAL_RELEASE_INTENTS, frozenset)


def test_terminal_set_includes_usher_halt_classes():
    expected_halt = {
        "usher-halt-merge-failure",
        "usher-halt-deploy-infra-failure",
        "usher-halt-deploy-stage-failure",
        "usher-halt-unexpected",
    }
    assert expected_halt.issubset(TERMINAL_RELEASE_INTENTS)
    assert expected_halt.isdisjoint(NON_TERMINAL_RELEASE_INTENTS)


def test_classify_usher_halt_intents_terminal():
    for intent in (
        "usher-halt-merge-failure",
        "usher-halt-deploy-infra-failure",
        "usher-halt-deploy-stage-failure",
        "usher-halt-unexpected",
    ):
        assert classify_release_intent(intent) == "terminal"
        assert is_non_terminal_release_intent(intent) is False


def test_terminal_and_non_terminal_sets_are_disjoint():
    assert NON_TERMINAL_RELEASE_INTENTS.isdisjoint(TERMINAL_RELEASE_INTENTS)


def test_is_non_terminal_true_for_readiness_check_blocked():
    assert is_non_terminal_release_intent("readiness-check-blocked") is True


def test_is_non_terminal_false_for_none():
    assert is_non_terminal_release_intent(None) is False


def test_is_non_terminal_false_for_terminal_completed():
    assert is_non_terminal_release_intent("completed") is False


def test_is_non_terminal_false_for_idea_complete():
    assert is_non_terminal_release_intent("idea-complete") is False


def test_is_non_terminal_false_for_operator_override():
    assert is_non_terminal_release_intent("operator-override") is False


def test_is_non_terminal_false_for_unknown_intent():
    assert is_non_terminal_release_intent("totally-made-up-intent") is False


def test_classify_returns_non_terminal_for_readiness_check_blocked():
    assert classify_release_intent("readiness-check-blocked") == "non_terminal"


def test_classify_returns_terminal_for_completed():
    assert classify_release_intent("completed") == "terminal"


def test_classify_returns_terminal_for_idea_complete():
    assert classify_release_intent("idea-complete") == "terminal"


def test_classify_returns_terminal_for_operator_override():
    assert classify_release_intent("operator-override") == "terminal"


def test_classify_returns_unknown_for_unrecognized_intent():
    assert classify_release_intent("totally-made-up-intent") == "unknown"


def test_classify_returns_unknown_for_none():
    assert classify_release_intent(None) == "unknown"

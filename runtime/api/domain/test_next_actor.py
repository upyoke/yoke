"""Responsibility follows durable obligations, not activity or heartbeat."""

from datetime import datetime, timezone

import pytest

from yoke_core.domain.next_actor import action, item_next_actor
from yoke_core.domain.session_state import session_state

NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize("executor", ["codex", "claude-code", "cursor"])
@pytest.mark.parametrize(
    "key,actor,reason",
    [
        ("pending_decision", "operator", "approve secret"),
        ("dependency_wait", "another_item", "dependency_unsatisfied"),
        ("deployment_wait", "ci_or_deploy", "release_run_in_progress"),
        ("ci_wait", "ci_or_deploy", "ci_run_in_progress"),
    ],
)
def test_session_and_item_share_external_action(key, actor, reason, executor):
    facts = {
        key: action(actor, reason, NOW),
        "executor": executor,
        "mode": "parked",
        "turn_posture": "waiting",
    }
    state = session_state(facts, now=NOW)
    assert state["next_actor"]["actor"] == actor
    assert state["next_actor"]["reason"] == reason
    assert state["next_actor"]["since"] == "2026-11-06T00:00:00.000000Z"
    assert state["intent"]["awaiting_who"] == actor
    assert item_next_actor(facts) == state["next_actor"]


def test_working_session_and_unclaimed_ready_item():
    state = session_state(
        {"turn_posture": "running", "last_tool_call_at": NOW}, now=NOW
    )
    assert state["next_actor"]["actor"] == "this_session"
    assert item_next_actor({})["actor"] == "parent_or_steering"
    assert (
        item_next_actor({}, holder={"turn_posture": "running"})["actor"]
        == "this_session"
    )


def test_terminal_state_clears_obligations_and_gone_process_needs_direction():
    pending = {"pending_decision": action("operator", "approve", NOW)}
    assert item_next_actor({**pending, "terminal": True})["actor"] == "nobody"
    assert (
        session_state({**pending, "ended_at": NOW}, now=NOW)["next_actor"]["actor"]
        == "nobody"
    )
    assert (
        session_state({"native_process_gone_at": NOW}, now=NOW)["next_actor"]["actor"]
        == "parent_or_steering"
    )


def test_priority_is_decision_then_dependency_then_ci_then_release():
    facts = {
        "pending_decision": action("operator", "approve"),
        "dependency_wait": action("another_item", "dependency"),
        "ci_wait": action("ci_or_deploy", "ci"),
        "deployment_wait": action("ci_or_deploy", "release"),
    }
    for key, reason in [
        ("pending_decision", "approve"),
        ("dependency_wait", "dependency"),
        ("ci_wait", "ci"),
        ("deployment_wait", "release"),
    ]:
        assert item_next_actor(facts)["reason"] == reason
        facts.pop(key)


@pytest.mark.parametrize("value", [None, False, 0, "0"])
def test_unset_item_flags_do_not_park_ready_work(value):
    assert (
        item_next_actor({"frozen": value, "blocked": value})["reason"]
        == "ready_without_holder"
    )


@pytest.mark.parametrize("flag", ["frozen", "blocked"])
def test_item_holds_keep_their_reason(flag):
    assert (
        item_next_actor({flag: "1", "blocked_reason": "scope decision"})["reason"]
        == "scope decision"
    )


def test_reason_sentences_preserve_free_text_and_translate_codes():
    from yoke_core.domain.next_actor import reason_sentence, REASON_SENTENCES

    for code, sentence in REASON_SENTENCES.items():
        assert reason_sentence(code) == sentence
        assert "_" not in sentence
        assert action("operator", code)["sentence"] == sentence
    assert reason_sentence("Please review the release") == "Please review the release"
    assert "gone" not in reason_sentence("session_process_gone")

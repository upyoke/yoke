"""The machine-wide event set follows the hook chains and their guard scopes.

Outside a project only machine-scope guards apply, so a user-level hook is
worth installing only on the session lifecycle events (registration, prompt
delivery, turn and session end), on the events whose chain carries a
machine guard, and on one mid-turn event that injects messages. Adding a
machine guard to another chain fails this test until the contract installs
that event too.
"""

from __future__ import annotations

import pytest

from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
from yoke_contracts.hook_runner.guard_scope import GuardScope, guard_scope
from yoke_contracts.hook_runner.hook_ordering import HOOK_ORDERING
from yoke_contracts.session_control.capabilities import capabilities_for_harness

LIFECYCLE_VERBS = {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"}
# Tool events that fire inside a running turn, in install preference order:
# the PreToolUse Bash hook is already installed for the machine guards.
MID_TURN_VERBS = ("PreToolUse", "PostToolUse")


def _mid_turn_delivery_verb(harness_id: str) -> str:
    """The first tool event every surface of the harness injects messages on."""
    surfaces = capabilities_for_harness(harness_id).values()
    for verb in MID_TURN_VERBS:
        if all(verb in surface["inject_events"] for surface in surfaces):
            return verb
    raise AssertionError(f"{harness_id} declares no mid-turn inject event")


def _machine_guard_pairs() -> set[tuple[str, str]]:
    return {
        (event, matcher)
        for event, chains in HOOK_ORDERING.items()
        for matcher, chain in chains.items()
        if any(guard_scope(module) is GuardScope.MACHINE for module in chain)
    }


def _deferred(spec, verb: str) -> bool:
    return any(note.startswith(f"{verb}:") for note in spec.deferrals)


@pytest.mark.parametrize("harness_id", sorted(HARNESS_MACHINE_HOOKS))
def test_every_machine_guard_chain_is_installed(harness_id):
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    pairs = _machine_guard_pairs()
    assert pairs, "no machine guard is registered in any hook chain"
    for verb, matcher in pairs:
        events = [event for event in spec.events if event.verb == verb]
        assert events, f"{harness_id} installs no {verb} hook for machine guards"
        # Claude and Codex filter by tool name; Cursor's shell event is Bash-only.
        assert all(event.matcher in (None, matcher) for event in events)


@pytest.mark.parametrize("harness_id", sorted(HARNESS_MACHINE_HOOKS))
def test_lifecycle_events_are_installed_or_deferred_by_name(harness_id):
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    installed = {event.verb for event in spec.events}
    for verb in LIFECYCLE_VERBS:
        assert verb in installed or _deferred(spec, verb), (harness_id, verb)


@pytest.mark.parametrize("harness_id", sorted(HARNESS_MACHINE_HOOKS))
def test_mid_turn_message_delivery_is_installed(harness_id):
    """A session outside a project receives messages before its turn ends."""
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    verb = _mid_turn_delivery_verb(harness_id)
    events = [event for event in spec.events if event.verb == verb]
    assert events, f"{harness_id} installs no {verb} hook for mid-turn messages"


def test_cursor_delivers_mid_turn_messages_on_matcherless_post_tool_use():
    spec = HARNESS_MACHINE_HOOKS["cursor"]
    assert _mid_turn_delivery_verb("cursor") == "PostToolUse"
    assert [
        (e.native_event, e.matcher) for e in spec.events if e.verb == "PostToolUse"
    ] == [("postToolUse", None)]


@pytest.mark.parametrize("harness_id", sorted(HARNESS_MACHINE_HOOKS))
def test_no_project_only_event_is_installed(harness_id):
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    allowed = (
        LIFECYCLE_VERBS
        | {verb for verb, _ in _machine_guard_pairs()}
        | {_mid_turn_delivery_verb(harness_id)}
    )
    assert {event.verb for event in spec.events} <= allowed


@pytest.mark.parametrize("harness_id", sorted(HARNESS_MACHINE_HOOKS))
def test_session_start_accepts_every_source(harness_id):
    events = [
        e for e in HARNESS_MACHINE_HOOKS[harness_id].events if e.verb == "SessionStart"
    ]
    assert events
    assert all(e.matcher is None for e in events)

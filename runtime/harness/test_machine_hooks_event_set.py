"""The machine-wide event set follows the hook chains and their guard scopes.

Outside a project only machine-scope guards apply, so a user-level hook is
worth installing only on the session lifecycle events (registration, prompt
delivery, turn and session end) and on the events whose chain carries a
machine guard. Adding a machine guard to another chain fails this test until
the contract installs that event too.
"""

from __future__ import annotations

import pytest

from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
from yoke_contracts.hook_runner.guard_scope import GuardScope, guard_scope
from yoke_contracts.hook_runner.hook_ordering import HOOK_ORDERING

LIFECYCLE_VERBS = {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"}


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
def test_no_project_only_event_is_installed(harness_id):
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    allowed = LIFECYCLE_VERBS | {verb for verb, _ in _machine_guard_pairs()}
    assert {event.verb for event in spec.events} <= allowed

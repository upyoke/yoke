"""A relay marks its own worker on every turn it starts for it.

The first turn carries the launch context. Every turn the relay restarted
after that one carries the resume-attempt id instead, because a resume is
spawned into a child environment scrubbed of inherited parent facts. Both
name a headless command whose turn is its whole life, so the watcher keeps
either one's wait inside the turn it was called from.
"""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

from yoke_core.tools._watch_wait_mode import (
    caller_is_headless_command,
    headless_marker_name,
    resolve_wait_mode,
)


def test_a_resumed_worker_keeps_the_wait_in_turn_without_its_launch_context() -> None:
    """The relay drops the launch context when it restarts its own worker.

    A resumed turn is spawned into a child environment scrubbed of inherited
    parent facts, so the resume-attempt id is the only marker left — and the
    caller is exactly as unpromptable as it was on its first turn.
    """
    mode = resolve_wait_mode(
        environ={RESUME_ATTEMPT_ENV: "job-1"},
        session_reader=lambda: pytest.fail("headless resume must not need a read"),
    )
    assert mode.name == "in-turn"
    assert "headless command" in mode.reason
    assert RESUME_ATTEMPT_ENV in mode.reason
    assert mode.headless is True


def test_only_a_relay_marker_marks_the_caller_headless() -> None:
    assert caller_is_headless_command({LAUNCH_CONTEXT_ENV: "{}"}) is True
    assert caller_is_headless_command({RESUME_ATTEMPT_ENV: "job-1"}) is True
    assert (
        caller_is_headless_command(
            {LAUNCH_CONTEXT_ENV: "{}", RESUME_ATTEMPT_ENV: "job-1"}
        )
        is True
    )
    assert caller_is_headless_command({LAUNCH_CONTEXT_ENV: "   "}) is False
    assert caller_is_headless_command({RESUME_ATTEMPT_ENV: "   "}) is False
    assert (
        caller_is_headless_command(
            {LAUNCH_CONTEXT_ENV: "   ", RESUME_ATTEMPT_ENV: "   "}
        )
        is False
    )
    assert caller_is_headless_command({}) is False


def test_the_environment_a_relay_resume_is_started_with_stays_in_turn(
    tmp_path, monkeypatch
) -> None:
    """The producer's own child environment is what the consumer reads.

    Asserting the marker against a hand-built dict would only prove the two
    descriptions agree. This starts a resume through the relay's real spawn
    path, captures the environment spawn hands the child (adapter dict plus
    the resume attempt stamp), and selects the wait mode from exactly that.
    """
    from yoke_harness.session_relay_claude_invocation import ClaudeNativeInvocation
    from yoke_harness import session_relay_claude_native
    from yoke_harness.session_relay_native_spawn import _child_environment

    monkeypatch.setenv(LAUNCH_CONTEXT_ENV, '{"launch_id": "parent-launch"}')
    started: list[dict[str, object]] = []
    monkeypatch.setattr(
        session_relay_claude_native,
        "spawn_supervised_native",
        lambda argv, **kwargs: started.append(kwargs) or None,
    )
    context = type("Context", (), {"job_id": "resume-job", "lease_id": "lease-1"})()
    invocation = ClaudeNativeInvocation(
        "claude",
        tmp_path,
        "native-session",
        "2.1.238",
        "wake up",
        resume=True,
    )

    session_relay_claude_native.spawn_claude_wake(context, invocation)

    kwargs = started[0]
    environment = _child_environment(
        kwargs["environment"],
        supervision_kind=str(kwargs.get("supervision_kind") or "resume"),
        attempt_id=str(kwargs["attempt_id"]),
    )
    assert LAUNCH_CONTEXT_ENV not in environment
    assert environment[RESUME_ATTEMPT_ENV] == "resume-job"
    mode = resolve_wait_mode(
        environ=environment,
        session_reader=lambda: pytest.fail("headless resume must not need a read"),
    )
    assert mode.name == "in-turn"
    assert mode.headless is True


def test_the_named_marker_is_the_one_the_caller_actually_carries() -> None:
    assert headless_marker_name({LAUNCH_CONTEXT_ENV: "{}"}) == LAUNCH_CONTEXT_ENV
    assert headless_marker_name({RESUME_ATTEMPT_ENV: "job-1"}) == RESUME_ATTEMPT_ENV
    assert headless_marker_name({}) == ""

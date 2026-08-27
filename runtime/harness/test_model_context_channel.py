"""The channel a hook's model-facing context rides, per harness."""

from __future__ import annotations

import pytest

from yoke_contracts.hook_runner.model_context_channel import (
    ADVISORY_CHANNEL,
    SESSION_OPENING_STDOUT_EVENTS,
    STDOUT_CHANNEL,
    model_context_channel,
)


@pytest.mark.parametrize("family", ["claude", "codex"])
@pytest.mark.parametrize("event_name", sorted(SESSION_OPENING_STDOUT_EVENTS))
def test_raw_stdout_harnesses_keep_the_stdout_channel(
    family: str, event_name: str
) -> None:
    assert (
        model_context_channel(
            executor_family=family,
            event_name=event_name,
            stdout_events=SESSION_OPENING_STDOUT_EVENTS,
        )
        == STDOUT_CHANNEL
    )


def test_envelope_harness_never_uses_stdout() -> None:
    """Cursor answers with one JSON object. Text appended beside it is not
    parseable, so it reaches no model - and the settlement layer, seeing it
    in the process's stdout, would still record the delivery as injected."""
    for event_name in sorted(SESSION_OPENING_STDOUT_EVENTS):
        assert (
            model_context_channel(
                executor_family="cursor",
                event_name=event_name,
                stdout_events=SESSION_OPENING_STDOUT_EVENTS,
            )
            == ADVISORY_CHANNEL
        )


def test_unrecognized_harness_gets_the_structured_channel() -> None:
    """A harness nobody has taught this contract about drops the context
    with an honest receipt rather than recording one that never arrived."""
    assert (
        model_context_channel(
            executor_family="some-new-harness",
            event_name="SessionStart",
            stdout_events=SESSION_OPENING_STDOUT_EVENTS,
        )
        == ADVISORY_CHANNEL
    )


def test_events_outside_the_caller_scope_use_the_structured_channel() -> None:
    assert (
        model_context_channel(
            executor_family="claude",
            event_name="PreToolUse",
            stdout_events=SESSION_OPENING_STDOUT_EVENTS,
        )
        == ADVISORY_CHANNEL
    )

"""The client's fleet-watcher observation follows each harness's wake model."""

from __future__ import annotations

import json

import pytest

from yoke_contracts import fleet_watcher_observation as observation
from yoke_contracts.fleet_watcher_observation import (
    FLEET_WATCHER_OBSERVATION_KEY,
    fleet_watcher_live,
    observe_fleet_watcher,
    observed_absent,
)
from yoke_core.tools import watch_fleet, watch_tail
from yoke_harness.hooks.deadline import start_hook_deadline
from yoke_harness.hooks.local_subset import evaluate_local_subset


SESSION = "session-top"
CAPTURES = f"/scratch/yoke/sessions/{SESSION}/runs/pid-9/watcher-captures"
RAW = f"{CAPTURES}/yoke-fleet.raw.abc.log"
PROGRESS = f"{CAPTURES}/yoke-fleet.progress.abc.log"
PROBE = f"python3 -m {observation.PROBE_MODULE} --project yoke"
WRAPPER = (
    f"python3 /bin/yoke --env prod watch fleet --raw-capture {RAW} "
    f"--progress-capture {PROGRESS} -- --project yoke"
)
TAIL = f"python3 /bin/yoke watch tail {PROGRESS}"
UNRELATED = ("zsh", "cursor", "python3 -m pytest")


def test_detection_tokens_match_the_live_watcher_modules() -> None:
    assert observation.PROBE_MODULE == watch_fleet.PROBE_MODULE
    assert observation.WRAPPER_MODULE == watch_fleet.WRAPPER_MODULE
    assert observation.CAPTURE_PREFIX == f"yoke-{watch_fleet.KIND}."
    assert observation.TAIL_MODULE == watch_tail.WRAPPER_MODULE


@pytest.mark.parametrize(
    ("harness", "cmdlines", "live"),
    [
        # Monitor: an expired subscription leaves the wrapper running.
        ("claude-code", (PROBE, WRAPPER), False),
        ("claude-code", (PROBE, WRAPPER, TAIL), True),
        ("claude-code", (TAIL,), False),
        # notify_on_output: the subscription is invisible to ps by design.
        ("cursor", (PROBE, WRAPPER), True),
        ("cursor", (WRAPPER,), False),
        # No idle wake: the in-turn wrapper is the watcher.
        ("codex", (PROBE, WRAPPER), True),
        ("codex", UNRELATED, False),
    ],
)
def test_liveness_follows_the_wake_model(harness, cmdlines, live) -> None:
    assert fleet_watcher_live(SESSION, harness, cmdlines) is live


def test_another_sessions_watcher_does_not_count() -> None:
    other = (PROBE, WRAPPER.replace(SESSION, "other"), TAIL.replace(SESSION, "other"))
    assert fleet_watcher_live(SESSION, "claude-code", other) is False


def test_observation_rides_only_model_visible_events() -> None:
    payload = {"session_id": SESSION}
    seen = observe_fleet_watcher(
        payload, executor="claude-code", event_name="PreToolUse", cmdlines=UNRELATED
    )
    assert seen == {
        FLEET_WATCHER_OBSERVATION_KEY: {"session_id": SESSION, "live": False}
    }
    assert observed_absent(seen, SESSION)
    assert (
        observe_fleet_watcher(
            payload, executor="claude-code", event_name="SessionEnd", cmdlines=UNRELATED
        )
        == {}
    )


def test_failed_process_listing_proves_nothing(monkeypatch) -> None:
    monkeypatch.setattr(observation, "list_process_cmdlines", lambda: ())
    seen = observe_fleet_watcher(
        {"session_id": SESSION}, executor="codex", event_name="PreToolUse"
    )
    assert seen == {}
    assert not observed_absent(seen, SESSION)


def test_relay_request_carries_the_observation(monkeypatch) -> None:
    """The HTTPS split ships the client's answer; the server only renders it."""
    monkeypatch.setattr(observation, "list_process_cmdlines", lambda: UNRELATED)
    stdin = json.dumps({"session_id": SESSION, "tool_name": "Bash", "tool_input": {}})

    relayed = evaluate_local_subset(
        "PreToolUse",
        stdin,
        "claude-code",
        None,
        start_hook_deadline(),
        defer_main_commit=True,
    )
    standalone = evaluate_local_subset(
        "PreToolUse", stdin, "claude-code", None, start_hook_deadline()
    )

    assert observed_absent(relayed.payload_extra or {}, SESSION)
    assert FLEET_WATCHER_OBSERVATION_KEY not in (standalone.payload_extra or {})

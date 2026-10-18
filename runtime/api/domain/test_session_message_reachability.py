"""Delivery descriptions follow turns, parks and manifest-backed wake support."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_message_reachability import message_reachability
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)


@pytest.mark.parametrize(
    "surface,version",
    [("codex-cli", "0.200.0"), ("claude-cli", "2.1.281"), ("cursor-cli", "2026.10.01")],
)
@pytest.mark.parametrize(
    "posture,expected",
    [
        ("running", "mid-turn — message waits until the turn ends"),
        ("waiting", "between turns — message wakes it"),
    ],
)
def test_supported_harnesses_share_the_turn_description(
    surface, version, posture, expected
):
    assert (
        message_reachability(
            {
                "executor_surface": surface,
                "executor_version": version,
                "turn_posture": posture,
            }
        )
        == expected
    )


@pytest.mark.parametrize("posture", [None, "unknown"])
def test_unknown_posture_never_claims_a_running_process(posture):
    assert (
        message_reachability({"turn_posture": posture})
        == "delivery state unknown — inspect session evidence"
    )


@pytest.mark.parametrize("mode", ["parked", "dash"])
def test_containment_is_abnormal_even_when_the_native_returned_zero(mode):
    row = {
        "mode": mode,
        "turn_posture": "waiting",
        "turn_posture_at": "2026-09-09T12:00:00Z",
        "native_process_gone_at": "2026-09-09T12:01:00Z",
        "native_process_gone_evidence": {
            "exit_code": 0,
            "containment_reason": "inactivity",
        },
    }
    assert current_native_process_observation(row) is not None
    assert message_reachability(row).startswith(
        "contained by sweep: inactivity, claims held; "
    )


@pytest.mark.parametrize(
    "surface,version",
    [
        ("codex-desktop", "26.814.41407"),
        ("claude-desktop", "1.32885.1"),
        ("cursor-desktop", "3.17.8"),
    ],
)
def test_operator_surfaces_do_not_promise_an_automatic_wake(surface, version):
    assert (
        message_reachability(
            {
                "executor_surface": surface,
                "executor_version": version,
                "turn_posture": "waiting",
            }
        )
        == "between turns — message needs operator input on this surface"
    )


def test_activity_after_the_exit_retires_the_wake_in_flight_description():
    row = {
        "turn_posture": "running",
        "native_process_gone_at": "2026-09-09T12:00:00Z",
        "last_tool_call_at": "2026-09-09T12:01:00Z",
    }
    assert (
        message_reachability(row, resuming=True)
        == "mid-turn — message waits until the turn ends"
    )

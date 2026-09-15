"""Which wait shape a watcher selects for the caller that asked.

Selection decides which invocation the caller is handed, never whether
the watched command runs — printing runs nothing in either mode, which
``test_watch_print_only_contract`` pins.

The deciding fact is the harness's own native background-command notification
primitive, recorded in the wake registry. Yoke's ability to reach the session
over a relay answers a different question and never gates this one, so a
desktop conversation selects exactly what its CLI sibling does. Only a
relay-launched worker — a headless command whose turn is its whole life —
and a harness with no or unverified idle wake keep the wait in turn.
"""

from __future__ import annotations

import pytest

from yoke_contracts.harness_wake_capability import HarnessWakeCapability
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_core.tools import _watch_wait_mode
from yoke_core.tools._watch_wait_mode import (
    HEADLESS_CONTINUATION_DIRECTIVE,
    resolve_wait_mode,
    wait_mode_for_session,
)


def _session(
    executor: str,
    *,
    surface: str,
    wake_available: bool = False,
    wake_authority: str = "native",
    reason: str = "hook_delivery",
) -> dict[str, object]:
    """One roster row carrying messageability the selector must ignore."""
    return {
        "session_id": "session-1",
        "executor": executor,
        "executor_surface": surface,
        "messageability": {
            "wake_available": wake_available,
            "wake_authority": wake_authority,
            "reason": reason,
        },
    }


def test_manifest_without_idle_wake_keeps_the_wait_in_turn() -> None:
    mode = wait_mode_for_session(
        _session("codex", surface="codex-cli", wake_available=True)
    )
    assert mode.name == "in-turn"
    assert "agent_wake.idle_wake=none" in mode.reason


@pytest.mark.parametrize(
    ("executor", "surface", "mechanism"),
    [
        ("claude-code", "claude-cli", "Monitor"),
        ("cursor", "cursor-cli", "notify_on_output"),
    ],
)
def test_native_idle_wake_selects_the_background_wait(
    executor: str,
    surface: str,
    mechanism: str,
) -> None:
    mode = wait_mode_for_session(
        _session(executor, surface=surface, wake_available=True)
    )
    assert mode.name == "background-wake"
    assert mode.wake_mechanism == mechanism
    assert "agent_wake.idle_wake=supported" in mode.reason
    assert mechanism in mode.reason


@pytest.mark.parametrize(
    ("executor", "surface", "mechanism"),
    [
        ("claude-code", "claude-desktop", "Monitor"),
        ("cursor", "cursor-desktop", "notify_on_output"),
    ],
)
def test_desktop_conversation_matches_its_cli_sibling(
    executor: str,
    surface: str,
    mechanism: str,
) -> None:
    """An operator-woken surface still runs the harness's own primitive.

    ``wake_authority=operator`` refuses a Yoke-driven relay resume, which is
    not what a background command notification does: the harness resumes its
    own turn in place, needing nothing from the control plane.
    """
    mode = wait_mode_for_session(
        _session(
            executor,
            surface=surface,
            wake_available=False,
            wake_authority="operator",
        )
    )
    assert mode.name == "background-wake"
    assert mode.wake_mechanism == mechanism


@pytest.mark.parametrize(
    "row",
    [
        _session(
            "claude-code",
            surface="claude-cli",
            wake_available=False,
            reason="version_below_floor_or_unknown",
        ),
        _session(
            "cursor",
            surface="cursor-cli",
            wake_available=False,
            reason="hook_delivery_unavailable",
        ),
        {"session_id": "session-1", "executor": "claude-code"},
    ],
)
def test_relay_routing_never_holds_a_natively_wakeable_harness(row) -> None:
    """Absent, unknown, and explicitly unreachable relay routes all pass."""
    assert wait_mode_for_session(row).name == "background-wake"


@pytest.mark.parametrize(
    "row",
    [None, {"session_id": "session-1", "executor": "brand-new-harness"}],
)
def test_unknown_harness_keeps_the_wait_in_turn(row) -> None:
    mode = wait_mode_for_session(row)
    assert mode.name == "in-turn"
    assert "unknown" in mode.reason


def test_unverified_wake_capability_keeps_the_wait_in_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _watch_wait_mode,
        "wake_capability_for_harness",
        lambda harness_id: HarnessWakeCapability(
            idle_wake="unverified",
            idle_wake_mechanism="",
            timer_wake="unverified",
            timer_wake_mechanism="",
            verified_on_surface="",
            evidence="no wake probe recorded",
        ),
    )
    mode = wait_mode_for_session(_session("cursor", surface="cursor-cli"))
    assert mode.name == "in-turn"
    assert "unverified" in mode.reason


def test_relay_launch_context_keeps_headless_worker_in_turn() -> None:
    mode = resolve_wait_mode(
        environ={LAUNCH_CONTEXT_ENV: "{}"},
        session_reader=lambda: pytest.fail("headless launch must not need a read"),
    )
    assert mode.name == "in-turn"
    assert "headless command" in mode.reason
    # The same selection carries who the caller is, so the runner can name
    # the continuation without reading the launch context a second way.
    assert mode.headless is True


def test_wait_mode_for_a_wakeable_harness_is_not_headless() -> None:
    mode = wait_mode_for_session(_session("claude-code", surface="claude-cli"))
    assert mode.headless is False
    assert wait_mode_for_session(None).headless is False


def test_the_continuation_directive_names_the_hand_back_and_the_recovery() -> None:
    directive = HEADLESS_CONTINUATION_DIRECTIVE
    assert "headless command whose turn is its whole life" in directive
    assert "background task or hands back a continuation handle" in directive
    assert "the command is still running" in directive
    assert "continue that same call" in directive
    assert "Reading the background task's output continues the call" in directive
    assert "only ending the turn kills this watcher" in directive
    assert "Never start a second invocation beside a live one" in directive


@pytest.mark.parametrize("surface", ["codex-cli", "codex-desktop"])
def test_codex_fleet_watch_keeps_cli_and_desktop_turns_active(surface):
    mode = wait_mode_for_session(
        _session("codex", surface=surface, wake_available=True)
    )
    assert mode.waits_in_turn
    assert mode.wake_mechanism == ""

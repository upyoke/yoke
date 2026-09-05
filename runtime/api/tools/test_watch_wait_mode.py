"""A watcher releases a caller whose harness can resume an ended turn.

The deciding fact is the harness's own native background-command notification
primitive, recorded in the wake registry. Yoke's ability to reach the session
over a relay answers a different question and never gates this one, so a
desktop conversation selects exactly what its CLI sibling does. Only a
relay-launched worker — a headless command whose turn is its whole life —
and a harness with no or unverified idle wake keep the wait in turn.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from yoke_contracts.harness_wake_capability import HarnessWakeCapability
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_core.tools import _watch_streaming_pair, watch_doctor, watch_fleet
from yoke_core.tools import _watch_wait_mode
from yoke_core.tools._watch_wait_mode import (
    WatchWaitMode,
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


@pytest.mark.parametrize(
    ("watcher", "engine_builder", "mode"),
    [
        (
            watch_fleet,
            "_probe_argv",
            wait_mode_for_session(
                _session("codex", surface="codex-cli", wake_available=True)
            ),
        ),
        (watch_doctor, "_doctor_argv", wait_mode_for_session(None)),
    ],
)
def test_in_turn_mode_runs_two_watchers_through_child_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    watcher,
    engine_builder: str,
    mode: WatchWaitMode,
) -> None:
    marker = tmp_path / f"{watcher.KIND}.finished"
    raw = tmp_path / f"{watcher.KIND}.raw"
    progress = tmp_path / f"{watcher.KIND}.progress"
    child = [
        sys.executable,
        "-c",
        (
            "import pathlib, time; time.sleep(0.05); "
            f"pathlib.Path({str(marker)!r}).write_text('done')"
        ),
    ]
    monkeypatch.setattr(
        _watch_streaming_pair,
        "resolve_wait_mode",
        lambda: mode,
    )
    monkeypatch.setattr(
        watcher._watch_runner,
        "mint_capture_paths",
        lambda kind: (raw, progress),
    )
    monkeypatch.setattr(watcher, engine_builder, lambda args: child)

    assert watcher.main(["--print-streaming-pair"]) == 0

    output = capsys.readouterr().out
    assert marker.read_text() == "done"
    assert f"# watch_{watcher.KIND} wait_mode=in-turn" in output
    assert "holding this turn until the watched command exits" in output
    assert "no completion wake is expected" in output


def test_wakeable_watcher_exits_to_its_conditional_completion_wake(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = tmp_path / "fleet.raw"
    progress = tmp_path / "fleet.progress"
    mode = wait_mode_for_session(
        _session("claude-code", surface="claude-cli", wake_available=True)
    )
    monkeypatch.setattr(
        _watch_streaming_pair,
        "resolve_wait_mode",
        lambda: mode,
    )
    monkeypatch.setattr(
        watch_fleet._watch_runner,
        "mint_capture_paths",
        lambda kind: (raw, progress),
    )
    monkeypatch.setattr(
        watch_fleet,
        "_probe_argv",
        lambda args: pytest.fail("wake mode must return before running the child"),
    )

    assert watch_fleet.main(["--print-streaming-pair"]) == 0

    output = capsys.readouterr().out
    assert "# watch_fleet wait_mode=background-wake" in output
    assert "completion wake is expected only because this harness" in output
    assert "yoke watch tail" in output

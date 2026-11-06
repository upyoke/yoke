"""A Monitor subscription expires; the recovery is the same tail, re-armed.

Claude Code ends every Monitor at its timeout_ms deadline (capped at 30
minutes), so a steering seat's standing tail lapses while its watcher keeps
running. The recipe said "arm ONCE, do NOT re-arm", the guard refused any
second arm for ten minutes, and the alert told the seat to print a fresh
pair — a second wrapper. The expiry is now a manifest fact, and every
surface follows it: arm at the cap, re-arm the same tail on the expiry
notice, never relaunch the wrapper. Harnesses without the limit keep their
own manifest answers.
"""

from __future__ import annotations

import io
from pathlib import Path

from yoke_contracts.fleet_watcher_observation import (
    FLEET_WATCHER_OBSERVATION_KEY,
    lapsed_tail_capture,
    observe_fleet_watcher,
    observed_lapsed_tail,
)
from yoke_contracts.harness_wake_capability import (
    HARNESS_WAKE_CAPABILITIES,
    wake_capability_for_mechanism,
)
from yoke_core.hooks.fleet_watcher_presence import (
    fleet_watcher_absent_nudge,
    lapsed_tail_nudge,
)
from yoke_core.tools._watch_streaming_pair import print_streaming_pair

SESSION = "session-top"
CAPTURES = f"/scratch/yoke/sessions/{SESSION}/runs/pid-9/watcher-captures"
RAW = f"{CAPTURES}/yoke-fleet.raw.abc.log"
PROGRESS = f"{CAPTURES}/yoke-fleet.progress.abc.log"
PROBE = "python3 -m yoke_core.domain.fleet_delta_probe --project yoke"
WRAPPER = (
    f"python3 /bin/yoke --env prod watch fleet --raw-capture {RAW} "
    f"--progress-capture {PROGRESS} -- --project yoke"
)
TAIL = f"python3 /bin/yoke watch tail {PROGRESS}"


def test_only_claude_declares_a_subscription_limit() -> None:
    claude = HARNESS_WAKE_CAPABILITIES["claude-code"]
    assert claude.subscription_limit_seconds(headless=False) == 1800
    assert claude.subscription_limit_seconds(headless=True) == 600
    assert claude.idle_wake_default_timeout_seconds == 300
    assert claude.idle_wake_deadline_parameter == "timeout_ms"
    for harness in ("codex", "cursor"):
        other = HARNESS_WAKE_CAPABILITIES[harness]
        assert other.subscription_limit_seconds(headless=False) is None
        assert other.subscription_limit_seconds(headless=True) is None
        assert other.idle_wake_deadline_parameter == ""
    assert wake_capability_for_mechanism("Monitor") is claude
    assert wake_capability_for_mechanism("") is None


def _recipe(mechanism: str, tmp_path: Path) -> str:
    out = io.StringIO()
    print_streaming_pair(
        kind="fleet",
        wrapper_module="yoke_core.tools.watch_fleet",
        wrapper_args=["--project", "yoke"],
        raw_capture=tmp_path / "raw.log",
        progress_capture=tmp_path / "progress.log",
        wake_mechanism=mechanism,
        out=out,
    )
    return out.getvalue()


def test_the_monitor_recipe_arms_at_the_cap_and_re_arms_on_expiry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.tools._watch_streaming_pair.caller_is_headless_command",
        lambda: False,
    )
    recipe = _recipe("Monitor", tmp_path)
    assert "timeout_ms=1800000" in recipe
    assert "On the expiry notice, re-arm this same tail" in recipe
    assert "never relaunch the wrapper" in recipe
    assert "for the lifetime of the bg command" not in recipe


def test_a_recipe_without_a_subscription_limit_keeps_arm_once(tmp_path: Path) -> None:
    recipe = _recipe("notify_on_output", tmp_path)
    assert "for the lifetime of the bg command" in recipe
    assert "timeout_ms" not in recipe


def test_a_lapsed_tail_names_the_running_wrappers_capture() -> None:
    assert lapsed_tail_capture(SESSION, (PROBE, WRAPPER)) == PROGRESS
    assert lapsed_tail_capture(SESSION, (PROBE, WRAPPER, TAIL)) == ""
    assert lapsed_tail_capture(SESSION, (PROBE,)) == ""

    payload = {"session_id": SESSION}
    observed = observe_fleet_watcher(
        payload,
        executor="claude-code",
        event_name="UserPromptSubmit",
        cmdlines=(PROBE, WRAPPER),
    )
    assert observed[FLEET_WATCHER_OBSERVATION_KEY]["lapsed_tail_capture"] == PROGRESS
    assert observed_lapsed_tail({**payload, **observed}, SESSION) == PROGRESS


def test_the_alert_re_arms_the_tail_instead_of_a_second_wrapper() -> None:
    alert = lapsed_tail_nudge("claude-code", PROGRESS)
    assert lapsed_tail_nudge("codex", PROGRESS) == ""
    assert f"yoke watch tail {PROGRESS}" in alert
    assert "timeout_ms=1800000" in alert
    assert "--print-streaming-pair" not in alert

    relaunch = fleet_watcher_absent_nudge(
        ("1",), SESSION, "claude-code", "UserPromptSubmit"
    )
    assert "--print-streaming-pair" in relaunch


def test_headless_recipe_and_alert_use_ten_minute_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "yoke_core.tools._watch_streaming_pair.caller_is_headless_command", lambda: True
    )
    recipe = _recipe("Monitor", tmp_path)
    assert "timeout_ms=600000" in recipe
    assert "timeout: 28800000" in recipe
    assert "timeout_ms=600000" in lapsed_tail_nudge(
        "claude-code", PROGRESS, headless=True
    )


def test_fleet_recipe_timeout_tracks_its_duration(tmp_path):
    out = io.StringIO()
    print_streaming_pair(
        kind="fleet",
        wrapper_module="yoke_core.tools.watch_fleet",
        wrapper_args=["--duration", "7200"],
        raw_capture=tmp_path / "raw",
        progress_capture=tmp_path / "progress",
        out=out,
    )
    assert "timeout: 7200000" in out.getvalue()

"""Bootout returns before the job does; these cover waiting it out.

A launch agent is torn down asynchronously: ``launchctl bootout`` returns
immediately, launchd sends SIGTERM, and only after ``ExitTimeOut`` does it
SIGKILL. A wait shorter than an ordinary teardown expires while the relay is
still shutting down, and the install then refuses to bootstrap the relay it
just stopped — which is what these tests pin down.
"""

from __future__ import annotations

from pathlib import Path
import plistlib
import subprocess

import pytest

from yoke_cli.config.session_relay_instance import (
    PROD_RELAY_LABEL,
    resolve_relay_instance,
)
from yoke_core.tools import launchctl_boundary as boundary
from yoke_core.tools.session_relay_legacy import (
    LegacyRelayError,
    retire_unpinned_legacy_relay,
)
from yoke_core.tools.session_relay_plist import (
    RelayInstallError,
    install_relay_launchd,
)

from .test_session_relay_plist import _config, _pin_release

TARGET = "gui/501/com.upyoke.relay.abc123"
#: Prints reporting "still loaded" for longer than the former 0.45s wait.
SLOW_TEARDOWN_PRINTS = round(0.5 / boundary.UNLOAD_POLL_INTERVAL_SECONDS) + 1


def _loaded_for(prints: int):
    """A launchctl runner reporting the job loaded for its first N prints."""
    remaining = prints

    def run(command, **_kwargs):
        nonlocal remaining
        loaded = str(command[1]) != "print" or remaining > 0
        if str(command[1]) == "print":
            remaining -= 1
        return subprocess.CompletedProcess(list(command), 0 if loaded else 1, "", "")

    return run


class _Clock:
    """A monotonic clock that only advances when the waiter pauses."""

    def __init__(self) -> None:
        self.elapsed = 0.0

    def pause(self, seconds: float) -> None:
        self.elapsed += seconds

    def now(self) -> float:
        return self.elapsed


def test_an_already_unloaded_job_returns_without_waiting_at_all() -> None:
    clock = _Clock()

    assert boundary.wait_for_launchd_unload(
        TARGET, run=_loaded_for(0), pause=clock.pause, now=clock.now
    )
    assert clock.elapsed == 0.0


def test_an_unload_past_the_former_half_second_limit_is_still_waited_out() -> None:
    clock = _Clock()

    assert boundary.wait_for_launchd_unload(
        TARGET,
        run=_loaded_for(SLOW_TEARDOWN_PRINTS),
        pause=clock.pause,
        now=clock.now,
    )
    assert clock.elapsed > 0.5


def test_a_job_that_never_unloads_fails_at_the_bound_not_forever() -> None:
    clock = _Clock()
    prints = 0

    def run(command, **_kwargs):
        nonlocal prints
        prints += 1
        return subprocess.CompletedProcess(list(command), 0, "", "")

    assert not boundary.wait_for_launchd_unload(
        TARGET, run=run, pause=clock.pause, now=clock.now
    )
    assert clock.elapsed >= boundary.UNLOAD_WAIT_SECONDS
    assert prints > 1


def _install(tmp_path: Path, runner):
    return install_relay_launchd(
        home=tmp_path,
        yoke_home=tmp_path / ".yoke",
        config_path=_config(tmp_path),
        environment="prod",
        pin_release=_pin_release,
        runner=runner,
        platform="darwin",
        uid=501,
    )


def test_install_bootstraps_after_a_teardown_that_outlives_a_sub_second_wait(
    tmp_path: Path,
) -> None:
    """A relay that takes its time shutting down still returns in one run."""
    calls: list[list[str]] = []
    teardown = _loaded_for(SLOW_TEARDOWN_PRINTS)

    def runner(command, **kwargs):
        calls.append([str(part) for part in command])
        if any(call[1] == "bootstrap" for call in calls):
            return subprocess.CompletedProcess(list(command), 0, "", "")
        return teardown(command, **kwargs)

    installed = _install(tmp_path, runner)

    verbs = [call[1] for call in calls]
    assert installed.loaded
    assert verbs.count("print") > SLOW_TEARDOWN_PRINTS
    assert verbs.index("bootstrap") > verbs.index("bootout")


def test_a_relay_that_stays_loaded_is_refused_before_any_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(boundary, "UNLOAD_WAIT_SECONDS", 0.0)
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append([str(part) for part in command])
        return subprocess.CompletedProcess(list(command), 0, "", "")

    with pytest.raises(RelayInstallError) as refusal:
        _install(tmp_path, runner)

    assert "kept the machine relay loaded after bootout" in str(refusal.value)
    assert "relay install" in str(refusal.value)
    assert "bootstrap" not in [call[1] for call in calls]


def test_a_legacy_relay_that_stays_loaded_keeps_its_plist_and_names_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy retirement probe waits out a teardown too, then teaches."""
    monkeypatch.setattr(boundary, "UNLOAD_WAIT_SECONDS", 0.0)
    legacy_path = tmp_path / "Library" / "LaunchAgents" / f"{PROD_RELAY_LABEL}.plist"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(plistlib.dumps({"Label": PROD_RELAY_LABEL}))

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(list(command), 0, "", "")

    with pytest.raises(LegacyRelayError) as refusal:
        retire_unpinned_legacy_relay(
            instance=resolve_relay_instance(
                config_path=_config(tmp_path),
                environment="stage",
                yoke_home=tmp_path / ".yoke",
            ),
            home=tmp_path,
            runner=runner,
            uid=501,
        )

    assert "kept the unpinned legacy machine relay loaded after bootout" in str(
        refusal.value
    )
    assert "yoke --env stage relay install" in str(refusal.value)
    assert legacy_path.exists()

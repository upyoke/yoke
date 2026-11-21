"""An active setup Apply holds CLI and checkout refresh until relay upkeep."""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

from yoke_cli.commands.adapters import session_control_relay_release
from yoke_cli.config import onboard_apply_lock, operator_cli_release_follow, self_update
from yoke_contracts.machine_config import relay_instance
from yoke_core.tools import session_relay_release
from yoke_harness import session_relay_daemon

RELEASE = "0.2.0.202611202031"


def test_relay_retries_a_deferred_follow_until_setup_releases_the_lock(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    instance = SimpleNamespace(
        environment="prod", state_dir=tmp_path, follows_served_release=True,
        machine_active=True,
    )
    monkeypatch.setattr(relay_instance, "resolve_relay_instance", lambda: instance)
    monkeypatch.setattr(
        session_relay_release, "relay_release_status",
        lambda **_kwargs: SimpleNamespace(
            current=True, pinned_release=RELEASE,
            runtime_python=Path(sys.prefix) / "bin" / "python",
        ),
    )
    follow = operator_cli_release_follow.follow_release
    launcher = tmp_path / "yoke"
    launcher.touch()
    version = "0.2.0.202611201926"
    actions = []

    def probe(argv, **_kwargs):
        actions.append("probe")
        return subprocess.CompletedProcess(argv, 0, stdout=version)

    def install(target, _launcher, *, env):
        nonlocal version
        actions.append("install")
        version = target

    def refresh(*_args):
        actions.append("refresh")
        return []

    monkeypatch.setattr(self_update, "resolve_target", lambda *, version: version)
    monkeypatch.setattr(self_update, "install_release", install)
    monkeypatch.setattr(operator_cli_release_follow, "_refresh_checkouts", refresh)
    monkeypatch.setattr(
        operator_cli_release_follow, "follow_release",
        lambda release, state_dir: follow(release, state_dir, run=probe, executable=launcher),
    )
    state = tmp_path / operator_cli_release_follow.FOLLOW_RECORD_NAME

    def serve_forever(*, cycle_maintenance, **_kwargs):
        assert json.loads(state.read_text())["outcome"] == "deferred_setup_active"
        cycle_maintenance()
        assert actions == []
        assert json.loads(state.read_text())["outcome"] == "deferred_setup_active"
        setup.close()
        cycle_maintenance()
        record = json.loads(state.read_text())
        assert record["outcome"] == "updated"
        assert record["after"] == RELEASE
        cycle_maintenance()

    monkeypatch.setattr(session_relay_daemon, "serve_forever", serve_forever)
    with ExitStack() as setup:
        setup.enter_context(onboard_apply_lock.acquire("setup"))
        session_control_relay_release.serve_release_daemon()
    assert actions == ["probe", "install", "probe", "refresh"]


def test_dead_setup_pid_does_not_block_release_follow(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    lock = onboard_apply_lock.lock_path()
    lock.parent.mkdir(parents=True)
    lock.write_text(json.dumps({"pid": -1}), encoding="utf-8")
    launcher = tmp_path / "yoke"
    launcher.touch()
    monkeypatch.setattr(operator_cli_release_follow, "_refresh_checkouts", lambda *_: [])

    def probe(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=RELEASE)

    record = operator_cli_release_follow.follow_release(
        RELEASE, tmp_path, run=probe, executable=launcher
    )

    assert record["outcome"] == "current"
    assert not lock.exists()

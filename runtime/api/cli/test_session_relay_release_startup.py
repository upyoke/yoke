"""Startup contracts for the standing relay's pinned release."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import session_control_relay as relay
from yoke_cli.commands.adapters import session_control_relay_release as release_cli
from yoke_cli.config import session_relay_instance
from yoke_core.tools import session_relay_release
from yoke_core.tools import session_relay_release_install
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RELAY_RELEASE_INSTALL_FAILED,
    RELAY_RELEASE_START_FAILED,
)
from yoke_harness import session_relay_daemon
from yoke_harness import session_relay_process_restart


def test_daemon_runs_from_pin_and_reloads_the_environment_release(
    monkeypatch,
    tmp_path,
) -> None:
    instance = SimpleNamespace(environment="stage", state_dir=tmp_path / "relay")
    pins: list[str] = []
    daemon_call = {}
    prepared: list[str] = []

    monkeypatch.setattr(
        session_relay_instance,
        "resolve_relay_instance",
        lambda: instance,
    )
    monkeypatch.setattr(
        session_relay_release,
        "relay_release_status",
        lambda **_kwargs: SimpleNamespace(
            current=True,
            pinned_release="0.1.1+launch.365",
            runtime_python=Path(sys.prefix) / "bin" / "python",
        ),
    )

    def pin(*, instance, served_build):
        pins.append(served_build)
        return SimpleNamespace(
            launch_executable=instance.state_dir / "venv" / "bin" / "yoke"
        )

    def serve_forever(**kwargs):
        daemon_call.update(kwargs)
        kwargs["cycle_maintenance"]()
        kwargs["cycle_maintenance"]()
        replacement = kwargs["pin_served_release"]("v0.1.1+launch.366")
        return SimpleNamespace(reason="served_build_changed", replacement=replacement)

    monkeypatch.setattr(session_relay_release_install, "pin_relay_release", pin)
    monkeypatch.setattr(session_relay_daemon, "serve_forever", serve_forever)

    outcome = release_cli.serve_release_daemon(
        cycle_maintenance=lambda: prepared.append("contained")
    )

    assert outcome.reason == "served_build_changed"
    assert prepared == ["contained", "contained"]
    assert daemon_call["state_dir"] == instance.state_dir
    assert daemon_call["pinned_release"] == "0.1.1+launch.365"
    assert daemon_call["reload_argv"] == ["--env", "stage", "relay", "serve"]
    assert pins == ["v0.1.1+launch.366"]


def test_source_serve_switches_to_the_pinned_executable(monkeypatch, tmp_path) -> None:
    instance = SimpleNamespace(environment="prod", state_dir=tmp_path / "relay")
    pinned_executable = instance.state_dir / "venv" / "bin" / "yoke"
    replacements: list[tuple[object, object]] = []
    prepared: list[str] = []
    monkeypatch.setattr(
        session_relay_instance,
        "resolve_relay_instance",
        lambda: instance,
    )
    monkeypatch.setattr(
        session_relay_release,
        "relay_release_status",
        lambda **_kwargs: SimpleNamespace(
            current=True,
            pinned_release="0.1.1+launch.365",
            runtime_python=instance.state_dir / "runtime" / "bin" / "python",
            launch_executable=pinned_executable,
        ),
    )
    monkeypatch.setattr(
        session_relay_process_restart,
        "exec_relay_release",
        lambda argv, *, executable: replacements.append((argv, executable)),
    )
    monkeypatch.setattr(
        session_relay_daemon,
        "serve_forever",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("source process ran the standing relay")
        ),
    )

    try:
        release_cli.serve_release_daemon(
            cycle_maintenance=lambda: prepared.append("contained")
        )
    except session_relay_release.RelayReleaseError as exc:
        assert exc.code == RELAY_RELEASE_START_FAILED
        assert "replacement returned" in str(exc)
    else:
        raise AssertionError("test replacement unexpectedly returned as success")
    assert replacements == [(["--env", "prod", "relay", "serve"], pinned_executable)]
    assert prepared == []


def test_existing_release_entrypoint_converges_before_stable_runtime_restart(
    monkeypatch,
    tmp_path,
) -> None:
    instance = SimpleNamespace(environment="prod", state_dir=tmp_path / "relay")
    prior_release = instance.state_dir / "releases" / "prior"
    prior_release.mkdir(parents=True)
    (instance.state_dir / "venv").symlink_to(prior_release, target_is_directory=True)
    launch_executable = instance.state_dir / "venv" / "bin" / "yoke"
    converged: list[object] = []
    replacements: list[tuple[object, object]] = []
    monkeypatch.setattr(
        session_relay_instance,
        "resolve_relay_instance",
        lambda: instance,
    )
    monkeypatch.setattr(
        session_relay_release,
        "relay_release_status",
        lambda **_kwargs: SimpleNamespace(
            current=False,
            pinned_release="",
            error_code="",
            error_message="",
        ),
    )

    def converge(*, instance):
        converged.append(instance)
        runtime = instance.state_dir / "runtime"
        (runtime / "bin").mkdir(parents=True)
        (instance.state_dir / "venv").unlink()
        (instance.state_dir / "venv").symlink_to(runtime, target_is_directory=True)
        return SimpleNamespace(
            current=True,
            pinned_release="0.1.1+launch.366",
            runtime_python=runtime / "bin" / "python",
            launch_executable=launch_executable,
        )

    monkeypatch.setattr(session_relay_release_install, "pin_relay_release", converge)
    monkeypatch.setattr(
        session_relay_process_restart,
        "exec_relay_release",
        lambda argv, *, executable: replacements.append((argv, executable)),
    )

    with pytest.raises(session_relay_release.RelayReleaseError, match="returned"):
        release_cli.serve_release_daemon()

    assert converged == [instance]
    assert replacements == [(["--env", "prod", "relay", "serve"], launch_executable)]


def test_post_deploy_restart_preserves_named_start_failure(
    monkeypatch,
    tmp_path,
) -> None:
    instance = SimpleNamespace(environment="prod", state_dir=tmp_path / "relay")
    python = Path(sys.prefix) / "bin" / "python"
    monkeypatch.setattr(
        session_relay_instance,
        "resolve_relay_instance",
        lambda: instance,
    )
    monkeypatch.setattr(
        session_relay_release,
        "relay_release_status",
        lambda **_kwargs: SimpleNamespace(
            current=True,
            pinned_release="0.1.1+launch.365",
            runtime_python=python,
        ),
    )
    monkeypatch.setattr(
        session_relay_process_restart,
        "exec_relay_release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("exec denied")),
    )

    def serve_forever(**kwargs):
        kwargs["reload_exec"](
            kwargs["reload_argv"],
            executable=instance.state_dir / "venv" / "bin" / "yoke",
        )

    monkeypatch.setattr(session_relay_daemon, "serve_forever", serve_forever)

    with pytest.raises(session_relay_release.RelayReleaseError) as raised:
        release_cli.serve_release_daemon()
    assert raised.value.code == RELAY_RELEASE_START_FAILED
    assert "exec denied" in str(raised.value)
    assert "relay install" in str(raised.value)


def test_daemon_refuses_without_a_working_release_pin(monkeypatch, tmp_path) -> None:
    instance = SimpleNamespace(environment="prod", state_dir=tmp_path / "relay")
    monkeypatch.setattr(
        session_relay_instance,
        "resolve_relay_instance",
        lambda: instance,
    )
    monkeypatch.setattr(
        session_relay_release,
        "relay_release_status",
        lambda **_kwargs: SimpleNamespace(
            current=False,
            pinned_release="",
            error_code="",
            error_message="",
        ),
    )

    try:
        release_cli.serve_release_daemon()
    except session_relay_release.RelayReleaseError as exc:
        assert exc.code == RELAY_RELEASE_INSTALL_FAILED
        assert "relay install" in str(exc)
    else:
        raise AssertionError("relay daemon started without a pinned release")


def test_daemon_preserves_the_recorded_pin_failure(monkeypatch, tmp_path) -> None:
    instance = SimpleNamespace(environment="prod", state_dir=tmp_path / "relay")
    monkeypatch.setattr(
        session_relay_instance,
        "resolve_relay_instance",
        lambda: instance,
    )
    monkeypatch.setattr(
        session_relay_release,
        "relay_release_status",
        lambda **_kwargs: SimpleNamespace(
            current=False,
            pinned_release="",
            error_code=RELAY_RELEASE_FETCH_FAILED,
            error_message="environment wheel index was unavailable",
        ),
    )

    try:
        release_cli.serve_release_daemon()
    except session_relay_release.RelayReleaseError as exc:
        assert exc.code == RELAY_RELEASE_FETCH_FAILED
        assert "wheel index was unavailable" in str(exc)
        assert "relay install" in str(exc)
    else:
        raise AssertionError("recorded relay pin failure was ignored")


def test_serve_command_preserves_named_release_refusal(monkeypatch, capsys) -> None:
    refusal = session_relay_release.RelayReleaseError(
        RELAY_RELEASE_INSTALL_FAILED,
        "relay release missing; recovery: run relay install",
    )
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(relay, "_contain_stranded_natives", lambda: None)
    monkeypatch.setattr(
        relay,
        "serve_release_daemon",
        lambda **_kwargs: (_ for _ in ()).throw(refusal),
    )

    assert relay.relay_serve(["--json"]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["code"] == RELAY_RELEASE_INSTALL_FAILED
    assert "run relay install" in payload["message"]


def test_serve_command_routes_containment_to_each_daemon_cycle(
    monkeypatch, capsys
) -> None:
    def contained() -> None:
        pass

    received = []
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(relay, "_contain_stranded_natives", contained)
    monkeypatch.setattr(
        relay,
        "serve_release_daemon",
        lambda *, cycle_maintenance: (
            received.append(cycle_maintenance)
            or session_relay_daemon.DaemonOutcome(reason="signal:SIGTERM")
        ),
    )

    assert relay.relay_serve(["--json"]) == 0
    assert received == [contained]
    assert json.loads(capsys.readouterr().out)["reason"] == "signal:SIGTERM"

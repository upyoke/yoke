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
            python=Path(sys.prefix) / "bin" / "python",
        ),
    )

    def pin(*, instance, served_build):
        pins.append(served_build)
        return SimpleNamespace(executable=instance.state_dir / "venv" / "bin" / "yoke")

    def serve_forever(**kwargs):
        daemon_call.update(kwargs)
        replacement = kwargs["pin_served_release"]("v0.1.1+launch.366")
        return SimpleNamespace(reason="served_build_changed", replacement=replacement)

    monkeypatch.setattr(session_relay_release_install, "pin_relay_release", pin)
    monkeypatch.setattr(session_relay_daemon, "serve_forever", serve_forever)

    outcome = release_cli.serve_release_daemon()

    assert outcome.reason == "served_build_changed"
    assert daemon_call["state_dir"] == instance.state_dir
    assert daemon_call["pinned_release"] == "0.1.1+launch.365"
    assert daemon_call["reload_argv"] == ["--env", "stage", "relay", "serve"]
    assert pins == ["v0.1.1+launch.366"]


def test_source_serve_switches_to_the_pinned_executable(monkeypatch, tmp_path) -> None:
    instance = SimpleNamespace(environment="prod", state_dir=tmp_path / "relay")
    pinned_executable = instance.state_dir / "venv" / "bin" / "yoke"
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
            current=True,
            pinned_release="0.1.1+launch.365",
            python=instance.state_dir / "venv" / "bin" / "python",
            executable=pinned_executable,
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
        release_cli.serve_release_daemon()
    except session_relay_release.RelayReleaseError as exc:
        assert exc.code == RELAY_RELEASE_START_FAILED
        assert "replacement returned" in str(exc)
    else:
        raise AssertionError("test replacement unexpectedly returned as success")
    assert replacements == [(["--env", "prod", "relay", "serve"], pinned_executable)]


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
            python=python,
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
        lambda: (_ for _ in ()).throw(refusal),
    )

    assert relay.relay_serve(["--json"]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["code"] == RELAY_RELEASE_INSTALL_FAILED
    assert "run relay install" in payload["message"]

"""CLI contracts for the standing relay's environment-owned release pin."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from yoke_cli.commands.adapters import session_control_relay as relay
from yoke_cli.commands.adapters import session_control_relay_release as release_cli
from yoke_cli.config import session_relay_instance
from yoke_cli.main import main as run_yoke_cli
from yoke_core.tools import session_relay_release
from yoke_core.tools import session_relay_release_install
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RELAY_RELEASE_INSTALL_FAILED,
)
from yoke_harness import session_relay_daemon


CURRENT_RELEASE = {
    "pinned_release": "0.1.1+launch.365",
    "served_build": "v0.1.1+launch.365",
    "release_current": True,
    "distribution_index": "https://api.upyoke.com/simple/",
    "release_error_code": None,
    "release_error": None,
    "release_recovery": None,
}


def _launchd_status(*, present: bool = True, current: bool = True):
    return SimpleNamespace(
        supported=True,
        environment="stage",
        label="com.upyoke.relay.abc123",
        plist_present=present,
        plist_current=current,
        loaded=present,
        plist_path=Path("/tmp/com.upyoke.relay.abc123.plist"),
        state_dir=Path("/tmp/relay-instances/abc123"),
    )


def test_relay_lifecycle_reports_release_pin(monkeypatch, capsys) -> None:
    monkeypatch.setattr(relay, "_plist_operation", lambda _action: _launchd_status())
    monkeypatch.setattr(
        relay,
        "release_status_payload",
        lambda _status, *, refresh_served: CURRENT_RELEASE,
    )

    assert relay.relay_install(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "distribution_index": "https://api.upyoke.com/simple/",
        "environment": "stage",
        "launchd_label": "com.upyoke.relay.abc123",
        "loaded": True,
        "pinned_release": "0.1.1+launch.365",
        "plist_current": True,
        "plist_path": "/tmp/com.upyoke.relay.abc123.plist",
        "plist_present": True,
        "release_current": True,
        "release_error": None,
        "release_error_code": None,
        "release_recovery": None,
        "served_build": "v0.1.1+launch.365",
        "state_dir": "/tmp/relay-instances/abc123",
        "supported": True,
    }


def test_relay_status_human_output_shows_pinned_and_served_build(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        relay,
        "_plist_operation",
        lambda _action: _launchd_status(current=False),
    )
    monkeypatch.setattr(
        relay,
        "release_status_payload",
        lambda _status, *, refresh_served: CURRENT_RELEASE,
    )

    assert relay.relay_status([]) == 1
    rendered = capsys.readouterr().out
    assert rendered.splitlines()[0] == "RELAY STATUS"
    assert "Pinned relay release" in rendered
    assert "0.1.1+launch.365" in rendered
    assert "Served build" in rendered
    assert "v0.1.1+launch.365" in rendered
    assert "Release pin current" in rendered
    assert "Distribution index" in rendered


def test_relay_status_fails_when_release_fetch_failed(monkeypatch, capsys) -> None:
    failed_release = {
        **CURRENT_RELEASE,
        "served_build": None,
        "release_current": False,
        "release_error_code": RELAY_RELEASE_FETCH_FAILED,
        "release_error": "distribution index unavailable",
        "release_recovery": "retry `yoke --env stage relay install`",
    }
    monkeypatch.setattr(relay, "_plist_operation", lambda _action: _launchd_status())
    monkeypatch.setattr(
        relay,
        "release_status_payload",
        lambda _status, *, refresh_served: failed_release,
    )

    assert relay.relay_status(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["pinned_release"] == "0.1.1+launch.365"
    assert payload["release_error_code"] == RELAY_RELEASE_FETCH_FAILED
    assert payload["release_recovery"]


def test_relay_status_fails_when_exact_instance_is_absent(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        relay,
        "_plist_operation",
        lambda _action: _launchd_status(present=False, current=False),
    )
    monkeypatch.setattr(
        relay,
        "release_status_payload",
        lambda _status, *, refresh_served: CURRENT_RELEASE,
    )

    assert relay.relay_status(["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["environment"] == "stage"


def test_global_env_selects_status_instance_then_restores_previous_env(
    monkeypatch,
    capsys,
) -> None:
    seen: list[tuple[str, str | None]] = []

    def operation(action: str):
        seen.append((action, os.environ.get("YOKE_ENV")))
        return _launchd_status()

    monkeypatch.setattr(relay, "_plist_operation", operation)
    monkeypatch.setattr(
        relay,
        "release_status_payload",
        lambda _status, *, refresh_served: CURRENT_RELEASE,
    )
    monkeypatch.setenv("YOKE_ENV", "prod")

    assert run_yoke_cli(["--env", "stage", "relay", "status", "--json"]) == 0
    assert seen == [("status", "stage")]
    assert os.environ["YOKE_ENV"] == "prod"
    assert json.loads(capsys.readouterr().out)["environment"] == "stage"


def test_lifecycle_preserves_named_release_install_error(monkeypatch, capsys) -> None:
    class ReleaseInstallFailed(RuntimeError):
        code = RELAY_RELEASE_FETCH_FAILED

    monkeypatch.setattr(
        relay,
        "_plist_operation",
        lambda _action: (_ for _ in ()).throw(
            ReleaseInstallFailed("served wheel could not be fetched")
        ),
    )

    assert relay.relay_install(["--json"]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["code"] == RELAY_RELEASE_FETCH_FAILED
    assert "served wheel" in payload["message"]


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
        lambda **_kwargs: SimpleNamespace(current=False, pinned_release=""),
    )

    try:
        release_cli.serve_release_daemon()
    except session_relay_release.RelayReleaseError as exc:
        assert exc.code == RELAY_RELEASE_INSTALL_FAILED
        assert "relay install" in str(exc)
    else:
        raise AssertionError("relay daemon started without a pinned release")


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

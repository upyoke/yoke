"""The installed CLI follows each release its active connection's relay starts on."""

from __future__ import annotations

from runtime.api.fixtures.machine_config_test import select_machine_config_file
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from yoke_cli.commands.adapters import session_control_relay_release as release_cli
from yoke_cli.config import (
    distribution,
    install_binding,
    operator_cli_release_follow as follow,
)
from yoke_cli.config import self_update, session_relay_instance
from yoke_cli.self_host import release_target
from yoke_cli.transport import installed_cli_staleness
from yoke_contracts.install_binding import KIND_PACKAGED_WHEEL
from yoke_core.tools import session_relay_release
from yoke_harness import session_relay_daemon


def _cli(tmp_path: Path, monkeypatch, versions: list[str], *, installs: bool = True):
    yoke = tmp_path / "yoke"
    yoke.write_text("", encoding="utf-8")
    installed: list[str] = []

    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=versions[0] + "\n")

    def install(target, _bin, *, env):
        installed.append(target)
        if not installs:
            raise self_update.SelfUpdateError("the Yoke installer failed (exit 1)")
        versions.pop(0)
        return versions[0]

    monkeypatch.setattr(self_update, "resolve_target", lambda *, version: version)
    monkeypatch.setattr(self_update, "install_release", install)
    return yoke, installed, run


def test_behind_cli_installs_exactly_the_observed_release(
    tmp_path, monkeypatch
) -> None:
    yoke, installed, run = _cli(
        tmp_path, monkeypatch, ["0.2.0.202610140940", "0.2.0.202610140941"]
    )
    record = follow.follow_release(
        "0.2.0.202610140941", tmp_path, run=run, executable=yoke
    )
    assert record["outcome"] == "updated"
    assert installed == ["0.2.0.202610140941"]
    stored = json.loads((tmp_path / follow.FOLLOW_RECORD_NAME).read_text())
    assert stored["after"] == "0.2.0.202610140941"


def test_probe_and_install_run_outside_the_relay_python(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "relay"
    release = state_dir / "releases" / "deadbeef"
    monkeypatch.setenv(session_relay_instance.RELAY_STATE_DIR_ENV, str(state_dir))
    monkeypatch.setenv("VIRTUAL_ENV", str(release))
    monkeypatch.setenv("PYTHONPATH", str(release / "site-packages"))
    monkeypatch.setenv("PATH", f"{state_dir / 'venv' / 'bin'}:/usr/bin")
    yoke = tmp_path / "yoke"
    yoke.write_text("", encoding="utf-8")
    envs: list[dict[str, str]] = []
    installed: list[str] = []

    def run(argv, *, env, **_kwargs):
        envs.append(env)
        # Inside the relay's activation the launcher reports the relay's release.
        moved = installed or "PYTHONPATH" in env
        version = "0.2.0.202610140943" if moved else "0.2.0.202610140942"
        return subprocess.CompletedProcess(argv, 0, stdout=version + "\n")

    def install(target, _bin, *, env):
        envs.append(env)
        installed.append(target)

    monkeypatch.setattr(self_update, "resolve_target", lambda *, version: version)
    monkeypatch.setattr(self_update, "install_release", install)
    record = follow.follow_release(
        "0.2.0.202610140943", tmp_path, run=run, executable=yoke
    )
    assert record["before"] == "0.2.0.202610140942"
    assert record["outcome"] == "updated"
    for env in envs:
        assert "PYTHONPATH" not in env and "VIRTUAL_ENV" not in env
        assert env["PATH"] == "/usr/bin"


def test_current_cli_is_left_alone(tmp_path, monkeypatch) -> None:
    yoke, installed, run = _cli(tmp_path, monkeypatch, ["0.2.0.202610140941"])
    record = follow.follow_release(
        "0.2.0.202610140941", tmp_path, run=run, executable=yoke
    )
    assert record["outcome"] == "current"
    assert installed == []


def test_a_hand_installed_development_build_is_moved_to_the_release(
    tmp_path, monkeypatch
) -> None:
    yoke, installed, run = _cli(
        tmp_path,
        monkeypatch,
        ["0.1.2.dev49+launch.621.g09b049c58", "0.2.0.202610140942"],
    )
    record = follow.follow_release(
        "0.2.0.202610140942", tmp_path, run=run, executable=yoke
    )
    assert record["outcome"] == "updated"
    assert installed == ["0.2.0.202610140942"]


def test_a_source_checkout_launcher_is_left_to_git(tmp_path, monkeypatch) -> None:
    yoke, installed, run = _cli(tmp_path, monkeypatch, ["source"])
    record = follow.follow_release(
        "0.2.0.202610140942", tmp_path, run=run, executable=yoke
    )
    assert record["outcome"] == "source_checkout"
    assert installed == []


def test_failed_install_names_the_recovery(tmp_path, monkeypatch, capsys) -> None:
    yoke, _installed, run = _cli(
        tmp_path, monkeypatch, ["0.2.0.202610140940"], installs=False
    )
    record = follow.follow_release(
        "0.2.0.202610140941", tmp_path, run=run, executable=yoke
    )
    assert record["outcome"] == "update_failed"
    err = capsys.readouterr().err
    assert "OPERATOR-CLI-FOLLOW-FAILED" in err
    assert "installer failed" in err
    assert "yoke update --version 0.2.0.202610140941" in err


def _https_config(tmp_path: Path, *, active_env: str) -> Path:
    """The connections an ordinary setup writes: https with no prod marker."""
    path = tmp_path / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    connections = {
        env: {
            "transport": "https",
            "api_url": f"https://{env}.example.test",
            "credential_source": {
                "kind": "token_file",
                "path": f"~/.yoke/secrets/{env}.token",
            },
        }
        for env in ("prod", "stage")
    }
    payload = {
        "schema_version": 1,
        "active_env": active_env,
        "connections": connections,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_only_the_active_connections_relay_is_machine_active(tmp_path) -> None:
    config = _https_config(tmp_path, active_env="prod")
    resolved = {
        env: session_relay_instance.resolve_relay_instance(
            config_path=config, environment=env, yoke_home=tmp_path / ".yoke"
        )
        for env in ("prod", "stage")
    }
    assert not resolved["prod"].prod
    assert resolved["prod"].machine_active
    assert not resolved["stage"].machine_active


def _serve_relay(monkeypatch, tmp_path, *, machine_active: bool) -> list[str]:
    instance = SimpleNamespace(
        environment="prod",
        state_dir=tmp_path,
        follows_served_release=True,
        machine_active=machine_active,
    )
    followed: list[str] = []
    monkeypatch.setattr(
        session_relay_instance, "resolve_relay_instance", lambda: instance
    )
    monkeypatch.setattr(
        session_relay_release,
        "relay_release_status",
        lambda **_k: SimpleNamespace(
            current=True,
            pinned_release="0.2.0.202610140941",
            runtime_python=Path(sys.prefix) / "bin" / "python",
        ),
    )
    monkeypatch.setattr(
        follow, "follow_release", lambda release, _d: followed.append(release)
    )
    monkeypatch.setattr(session_relay_daemon, "serve_forever", lambda **_k: "served")
    assert release_cli.serve_release_daemon() == "served"
    return followed


def test_active_connection_relay_start_follows_its_pinned_release(
    monkeypatch, tmp_path
) -> None:
    followed = _serve_relay(monkeypatch, tmp_path, machine_active=True)
    assert followed == ["0.2.0.202610140941"]


def test_other_relays_leave_the_installed_cli_alone(monkeypatch, tmp_path) -> None:
    assert _serve_relay(monkeypatch, tmp_path, machine_active=False) == []


def test_update_installs_the_requested_version_from_the_recorded_origin(
    monkeypatch, tmp_path
) -> None:
    select_machine_config_file(monkeypatch, tmp_path / "config.json")
    distribution.save(origin="https://fork.example", channel="stable")
    monkeypatch.setattr(
        install_binding,
        "detect",
        lambda: {"kind": KIND_PACKAGED_WHEEL, "version": "1.0.0"},
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _: "/bin/yoke")
    monkeypatch.setattr(
        release_target,
        "channel_release_target",
        lambda **_k: release_target.ReleaseTarget(
            version="1.2.0",
            source_commit="c",
            image="i",
            base_url="https://fork.example",
            channel="stable",
            installer_url="https://fork.example/dist/install.py",
        ),
    )
    installed: list[str] = []

    def stop(target):
        installed.append(target.version)
        raise release_target.ReleaseTargetError("stop before fetching")

    monkeypatch.setattr(release_target, "fetch_installer", stop)
    try:
        self_update.run_update(version="1.1.0.202610140941")
    except self_update.SelfUpdateError:
        pass
    assert installed == ["1.1.0.202610140941"]


def test_stale_cli_warns_once_and_only_against_the_active_connection(
    monkeypatch, tmp_path
) -> None:
    select_machine_config_file(monkeypatch, _https_config(tmp_path, active_env="prod"))
    monkeypatch.setattr(installed_cli_staleness, "_warned", False)
    stream = io.StringIO()
    kwargs = dict(
        server_version="0.2.0.202610140941", local_version="0.2.0.202610140940"
    )
    warn = installed_cli_staleness.warn_if_behind_active_connection
    assert not warn(env="stage", stream=stream, **kwargs)
    assert warn(env="prod", stream=stream, **kwargs)
    assert not warn(env="prod", stream=stream, **kwargs)
    assert "yoke update --version 0.2.0.202610140941" in stream.getvalue()
    assert "active connection 'prod'" in stream.getvalue()


def test_current_cli_does_not_warn(monkeypatch) -> None:
    monkeypatch.setattr(installed_cli_staleness, "_warned", False)
    assert not installed_cli_staleness.warn_if_behind_active_connection(
        env="prod",
        active_env="prod",
        server_version="0.2.0.202610140941",
        local_version="0.2.0.202610140941",
    )

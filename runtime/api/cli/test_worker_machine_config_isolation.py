"""A launched worker and its children cannot mutate a foreign machine config."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from yoke_contracts.machine_config import reader as client
from yoke_cli.config import writer
from yoke_cli.config.project_onboard_support import machine_config_path
from yoke_contracts.machine_config import runtime
from yoke_harness.session_relay_environment import native_session_environment


def _seed(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": {
                    name: {
                        "transport": "https",
                        "api_url": f"https://{name}.example",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(path.parent / f"{name}.token"),
                        },
                    }
                    for name in ("prod", "stage")
                },
            }
        )
    )
    return path.read_bytes()


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_launched_worker_and_cli_child_preserve_steering_config(tmp_path, executor):
    steering = tmp_path / "steering" / "config.json"
    original = _seed(steering)
    home = tmp_path / "worker"
    _seed(home / "config.json")
    environment = native_session_environment(
        executor=executor,
        environ={**os.environ, "YOKE_MACHINE_CONFIG_FILE": str(steering)},
        markers={"YOKE_MACHINE_HOME": str(home)},
    )
    assert "YOKE_MACHINE_CONFIG_FILE" not in environment
    for extra, expected in (([], 0), (["--config", str(steering)], 1)):
        result = subprocess.run(
            [sys.executable, "-m", "yoke_cli.main", "env", "use", "stage", *extra],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == expected, result.stderr
        if expected:
            assert "machine_config_not_owned" in result.stderr
            assert "remove --config" in result.stderr
        assert steering.read_bytes() == original
    assert json.loads((home / "config.json").read_text())["active_env"] == "stage"
    assert not steering.with_suffix(".json.lock").exists()


@pytest.mark.parametrize("resolver", [client, runtime])
def test_isolated_home_wins_over_stale_absolute_config_env(
    tmp_path, monkeypatch, resolver
):
    home = tmp_path / "worker"
    steering = tmp_path / "steering" / "config.json"
    _seed(steering)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(steering))
    assert resolver.config_path() == home / "config.json"
    assert resolver.load_config() == {}
    assert resolver.config_path("custom.json") == home / "custom.json"


@pytest.mark.parametrize("operation", ["active", "set", "remove", "auth", "runtime"])
def test_foreign_config_mutations_refuse_before_writing(
    tmp_path, monkeypatch, operation
):
    steering = tmp_path / "steering" / "config.json"
    original = _seed(steering)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "worker"))
    calls = {
        "active": lambda: writer.set_active_env("stage", path=steering),
        "set": lambda: writer.set_connection("local", transport="https", path=steering),
        "remove": lambda: writer.remove_connection("stage", path=steering),
        "auth": lambda: writer.set_credential(
            "prod", token="test-token", path=steering
        ),
        "runtime": lambda: runtime.write_config(steering, {"active_env": "local"}),
    }
    with pytest.raises(RuntimeError, match="machine_config_not_owned"):
        calls[operation]()
    assert steering.read_bytes() == original
    assert not steering.with_suffix(".json.lock").exists()


def test_a_config_symlink_cannot_escape_the_selected_home(tmp_path, monkeypatch):
    home = tmp_path / "worker"
    home.mkdir()
    steering = tmp_path / "steering" / "config.json"
    original = _seed(steering)
    (home / "config.json").symlink_to(steering)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    with pytest.raises(
        writer.MachineConfigWriteError, match="machine_config_not_owned"
    ):
        writer.set_active_env("stage")
    assert steering.read_bytes() == original


def test_default_home_cannot_write_a_foreign_explicit_config(tmp_path, monkeypatch):
    steering = tmp_path / "steering" / "config.json"
    original = _seed(steering)
    monkeypatch.delenv("YOKE_MACHINE_HOME", raising=False)
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "worker")
    with pytest.raises(
        writer.MachineConfigWriteError, match="machine_config_not_owned"
    ):
        writer.set_active_env("stage", path=steering)
    assert steering.read_bytes() == original


def test_deliberately_selected_shared_config_can_be_written(tmp_path, monkeypatch):
    shared = tmp_path / "shared" / "config.json"
    _seed(shared)
    monkeypatch.delenv("YOKE_MACHINE_HOME", raising=False)
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(shared))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "worker")
    writer.set_active_env("stage", path=shared)
    assert json.loads(shared.read_text())["active_env"] == "stage"


def test_explicit_dispatch_read_does_not_authorize_a_foreign_write(
    tmp_path, monkeypatch
):
    steering = tmp_path / "steering" / "custom.json"
    original = _seed(steering)
    home = tmp_path / "worker"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    with machine_config_path(steering):
        assert client.config_path() == steering
        assert runtime.config_path() == steering
        assert client.load_config()["active_env"] == "prod"
        with pytest.raises(
            writer.MachineConfigWriteError, match="machine_config_not_owned"
        ):
            writer.set_active_env("stage")
    assert client.config_path() == home / "config.json"
    assert steering.read_bytes() == original

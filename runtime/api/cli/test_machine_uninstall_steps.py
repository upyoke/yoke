"""Failure isolation, backup safety, and reuse of teardown surfaces."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from yoke_cli.config import machine_uninstall_steps as steps
from yoke_cli.config.machine_uninstall_inventory import Inventory, UninstallError


@pytest.fixture
def machine(tmp_path, monkeypatch):
    home = tmp_path / "machine"
    home.mkdir()
    config = home / "config.json"
    config.write_text("{}")
    value = Inventory(
        home,
        config,
        (tmp_path / "project",),
        ("remote",),
        True,
        "local",
        ((tmp_path / "server", "self-host"),),
    )
    calls, handoff_events = [], []
    handoff = SimpleNamespace(
        log=tmp_path / "result.log",
        arm=lambda: handoff_events.append("armed"),
        cancel=lambda: handoff_events.append("cancelled"),
    )
    monkeypatch.setattr(steps, "command", lambda args: calls.append(args))
    monkeypatch.setattr(
        steps.machine_uninstall_workers, "stop", lambda envs: calls.append(["workers"])
    )
    monkeypatch.setattr(steps.machine_uninstall_detached, "prepare", lambda: handoff)
    return value, calls, handoff_events


def test_complete_cleanup_removes_home_and_hands_off_cli(machine):
    value, calls, handoff = machine
    output = []
    assert steps.remove(value, value.projects, output.append) == 0
    assert not value.home.exists()
    assert calls[0] == ["--env", "remote", "relay", "uninstall"]
    assert calls[1] == ["workers"]
    assert ["ui", "down"] in calls
    assert ["local-postgres", "stop"] in calls
    teardown = next(args for args in calls if args[:2] == ["self-host", "teardown"])
    assert "--destroy-universe" in teardown and "--yes" in teardown
    assert handoff == ["armed"]
    assert "handed off" in output[-3]
    assert output[-1] == steps.NOT_REMOVED


def test_one_failure_does_not_hide_other_cleanup_and_keeps_recovery(
    machine, monkeypatch
):
    value, calls, handoff = machine

    def command(args):
        calls.append(args)
        if args[:2] == ["project", "uninstall"]:
            raise OSError("checkout is read-only")

    monkeypatch.setattr(steps, "command", command)
    output = []
    assert steps.remove(value, value.projects, output.append) == 1
    assert ["ui", "down"] in calls
    assert any(args[:2] == ["self-host", "teardown"] for args in calls)
    assert value.config.is_file()
    assert not handoff
    assert any("project" in line and "failed" in line for line in output)
    assert any("CLI: skipped" in line for line in output)


def test_cli_spawn_failure_keeps_machine_home(machine, monkeypatch):
    value, _, _ = machine
    monkeypatch.setattr(
        steps.machine_uninstall_detached,
        "prepare",
        lambda: steps._fail("spawn refused"),
    )
    assert steps.remove(value, (), lambda line: None) == 1
    assert value.config.is_file()


def test_backup_exports_each_actual_env_and_never_active_default(
    machine, tmp_path, monkeypatch
):
    value, calls, _ = machine
    monkeypatch.chdir(tmp_path)
    steps.back_up(value, lambda line: None)
    assert [args[1] for args in calls] == ["local", "self-host"]
    assert all(args[2:4] == ["universe", "export"] for args in calls)
    assert all(args[-1] == str(tmp_path) + "/" for args in calls)


def test_backup_failure_stops_destructive_removal(machine, tmp_path, monkeypatch):
    value, _, _ = machine
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(steps, "command", lambda args: steps._fail("export refused"))
    output = []
    with pytest.raises(UninstallError, match="uninstall_backup_failed"):
        steps.back_up(value, output.append)
    assert len([line for line in output if "failed" in line]) == 2
    assert value.config.is_file()


def test_backup_never_lands_inside_deleted_home(machine, monkeypatch):
    value, _, _ = machine
    monkeypatch.chdir(value.home)
    with pytest.raises(UninstallError, match="uninstall_backup_inside_home"):
        steps.back_up(value, lambda line: None)


def test_docker_discovery_failure_keeps_recovery_state(machine):
    value, calls, handoff = machine
    value = replace(
        value,
        bundles=(),
        discovery_error="uninstall_docker_inventory_failed: start Docker",
    )
    assert steps.remove(value, (), lambda line: None) == 1
    assert value.config.is_file()
    assert ["ui", "down"] in calls
    assert not handoff


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"connections": {}},
        {"github": {"api_url": "https://api.github.com"}, "connections": {}},
    ],
)
def test_half_setup_skips_github_and_completes_removal(machine, payload):
    value, calls, handoff = machine
    value.config.write_text(json.dumps(payload))
    value = replace(value, projects=(), relay_envs=(), local_universe=False, bundles=())
    output = []
    assert steps.remove(value, (), output.append) == 0
    assert not any(args[:2] == ["github", "disconnect"] for args in calls)
    assert any(line.startswith("GitHub: skipped (") for line in output)
    assert not value.home.exists()
    assert handoff == ["armed"]


def test_configured_github_uses_existing_disconnect(machine):
    value, calls, _ = machine
    value.config.write_text(
        json.dumps(
            {
                "github": {"api_url": "https://api.github.com"},
                "active_env": "remote",
                "connections": {"remote": {"transport": "https"}},
            }
        )
    )
    assert steps.remove(value, (), lambda _: None) == 0
    assert ["github", "disconnect", "--config", str(value.config)] in calls

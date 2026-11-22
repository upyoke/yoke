# ruff: noqa: F811 - pytest injects the re-exported fixtures
"""The scoped teardown preserves recovery authority and unrelated installations."""

import json
import subprocess

import pytest

from runtime.api.cli.self_host_teardown_test_support import (  # noqa: F401
    identity_probe,
    installation_commands,
    machine_home,
    payload,
    seed_connection,
    target,
)
from yoke_cli.config import machine_uninstall_steps, writer
from yoke_cli.config.machine_uninstall_inventory import UninstallError, remove_home_except_bundle
from yoke_cli.self_host import bundle, teardown


pytestmark = [
    pytest.mark.posix_only(reason="self-host server runs on POSIX"),
    pytest.mark.usefixtures("identity_probe", "installation_commands"),
]


@pytest.fixture()
def installed(tmp_path, machine_home, monkeypatch, installation_commands):
    config = machine_home / "config.json"
    seed_connection(tmp_path, env="team", api_url="http://127.0.0.1:8765")
    seed_connection(tmp_path, env="cloud", api_url="https://app.upyoke.com")
    projects = (tmp_path / "first", tmp_path / "second")
    saved = payload(machine_home)
    saved["connection_projects"] = {
        "team": [
            {"checkout": str(checkout), "project_id": index}
            for index, checkout in enumerate(projects, 1)
        ],
        "cloud": [{"checkout": str(tmp_path / "cloud"), "project_id": 1}],
    }
    config.write_text(json.dumps(saved), encoding="utf-8")

    def compose(argv, **kwargs):
        installation_commands.append(("docker", *argv[1:]))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(teardown, "_WHICH", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(teardown, "_RUN", compose)
    return config, projects, installation_commands


def test_scoped_teardown_uninstalls_layers_before_retiring_authority(
    target, installed, machine_home
):
    config, projects, calls = installed

    def retire(envs, **kwargs):
        calls.append(("retire", *envs))
        return writer.remove_connections(envs, **kwargs)

    report = teardown.tear_down(
        directory=str(target),
        config_path=str(config),
        activate="cloud",
        remove_connections=retire,
    )

    checks = [
        (
            "yoke",
            "project",
            "uninstall",
            str(path),
            "--config",
            str(config),
            "--remove-lanes",
            "--check",
            "--json",
        )
        for path in projects
    ]
    assert calls == [
        *checks,
        ("yoke", "--env", "team", "relay", "uninstall"),
        *(tuple(arg for arg in check if arg != "--check") for check in checks),
        ("retire", "team"),
        ("docker", "compose", "down"),
    ]
    assert report["relays_removed"] == ["team"]
    assert report["projects_uninstalled"] == [str(path) for path in projects]
    assert report["machine_uninstall"] == []
    assert set(payload(machine_home)["connections"]) == {"cloud"}
    assert set(payload(machine_home)["connection_projects"]) == {"cloud"}


@pytest.mark.parametrize("failure", ["preflight", "relay", "project"])
def test_refused_cleanup_keeps_server_and_authority(
    target, installed, monkeypatch, failure
):
    config, projects, calls = installed
    before = config.read_bytes()

    def command(args, **kwargs):
        calls.append(tuple(args))
        if failure == "preflight" and "--check" in args and str(projects[1]) in args:
            raise UninstallError("checkout has a dirty lane")
        if failure == "relay" and "relay" in args:
            raise UninstallError("repair the relay user service")
        if failure == "project" and args[0] == "project" and "--check" not in args:
            raise UninstallError("repair the checkout and retry project uninstall")

    monkeypatch.setattr(machine_uninstall_steps, "command", command)
    diagnostic = {
        "preflight": "dirty lane",
        "relay": "relay user service",
        "project": "retry project uninstall",
    }[failure]
    with pytest.raises(teardown.SelfHostTeardownError, match=diagnostic):
        teardown.tear_down(
            directory=str(target), config_path=str(config), activate="cloud"
        )

    assert config.read_bytes() == before
    assert (target / bundle.COMPOSE_FILE_NAME).is_file()
    assert all(call[0] != "docker" for call in calls)
    if failure == "preflight":
        assert len(calls) == 2
        assert all("--check" in call for call in calls)


def test_keep_connection_skips_project_relay_and_machine_uninstall(target, installed):
    config, _, calls = installed
    before = config.read_bytes()

    report = teardown.tear_down(
        directory=str(target), config_path=str(config), keep_connection=True
    )

    assert calls == [("docker", "compose", "down")]
    assert config.read_bytes() == before
    assert report["relays_removed"] == []
    assert report["projects_uninstalled"] == []
    assert report["machine_uninstall"] == []


def test_last_connection_hands_off_full_uninstall_after_compose_down(
    target, installed, machine_home
):
    config, _, calls = installed
    writer.remove_connection("cloud", path=config)

    report = teardown.tear_down(directory=str(target), config_path=str(config))

    assert calls[-2:] == [
        ("docker", "compose", "down"),
        ("uninstall", config, target),
    ]
    assert payload(machine_home)["connections"] == {}
    assert report["machine_uninstall"] == ["CLI: handed off"]
    assert (target / bundle.COMPOSE_FILE_NAME).is_file()


def test_machine_cleanup_preserves_nested_bundle(tmp_path):
    home = tmp_path / "machine"
    bundle_dir = home / "servers" / "local"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "compose.yml").touch()
    (bundle_dir.parent / "other-file").touch()
    (home / "config.json").touch()
    (home / "relay").mkdir()

    remove_home_except_bundle(home, bundle_dir)

    assert list(home.iterdir()) == [bundle_dir.parent]
    assert list(bundle_dir.parent.iterdir()) == [bundle_dir]
    assert list(bundle_dir.iterdir()) == [bundle_dir / "compose.yml"]


def test_failed_machine_handoff_keeps_bundle_for_retry(
    target, installed, monkeypatch
):
    config, _, calls = installed
    writer.remove_connection("cloud", path=config)

    def fail(**kwargs):
        raise UninstallError("repair the CLI uninstall handoff")

    monkeypatch.setattr(
        "yoke_cli.config.machine_uninstall.after_self_host_teardown", fail
    )

    with pytest.raises(teardown.SelfHostTeardownError, match="repair the CLI"):
        teardown.tear_down(
            directory=str(target), config_path=str(config), remove_bundle=True
        )

    assert calls[-1] == ("docker", "compose", "down")
    assert (target / bundle.COMPOSE_FILE_NAME).is_file()

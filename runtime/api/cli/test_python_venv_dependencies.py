"""Linux setup repairs missing ensurepip before installing relay packages."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import python_venv_dependencies as deps
from yoke_harness import system_privileges as privileges
from yoke_core.tools import session_relay_runtime_install as relay


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(deps.sys, "platform", "linux")
    monkeypatch.setattr(privileges.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(deps.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(deps.sys, "stderr", SimpleNamespace(isatty=lambda: False))
    commands = []
    ready = iter([False, True])

    def run(command, **kwargs):
        commands.append((command, kwargs))
        output = (
            json.dumps({"version": "3.12", "ready": next(ready)})
            if "-c" in command
            else ""
        )
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(deps.subprocess, "run", run)
    return commands


def test_missing_ensurepip_installs_actual_interpreter_package_and_rechecks(setup):
    deps.ensure_venv_support("/relay/runtime/bin/python", emit=lambda _: None)
    commands = [command for command, _ in setup]
    assert commands[0][0] == commands[-1][0] == "/relay/runtime/bin/python"
    assert commands[2] == ["/usr/bin/sudo", "-n", "--", "/usr/bin/apt-get", "update"]
    assert commands[3][-3:] == ["install", "-y", "python3.12-venv"]
    assert setup[3][1]["capture_output"] is True


def test_present_venv_needs_no_package_authority(setup, monkeypatch):
    monkeypatch.setattr(deps, "_probe", lambda _: {"version": "3.12", "ready": True})
    deps.ensure_venv_support(emit=lambda _: None)
    assert setup == []


def test_root_and_interactive_install_reuse_os_authority(setup, monkeypatch):
    monkeypatch.setattr(privileges.os, "geteuid", lambda: 0)
    deps.ensure_venv_support(emit=lambda _: None)
    assert all("sudo" not in command[0] for command, _ in setup)


def test_interactive_install_inherits_terminal(setup, monkeypatch):
    monkeypatch.setattr(deps.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(deps.sys, "stderr", SimpleNamespace(isatty=lambda: True))
    original = deps.subprocess.run

    def run(command, **kwargs):
        if command[1:] == ["-n", "true"]:
            return subprocess.CompletedProcess(command, 1, "", "password required")
        return original(command, **kwargs)

    monkeypatch.setattr(deps.subprocess, "run", run)
    deps.ensure_venv_support(emit=lambda _: None)
    install, kwargs = setup[2]
    assert install[:2] == ["/usr/bin/sudo", "--"]
    assert kwargs["capture_output"] is False


def test_no_authority_names_package_without_installing(setup, monkeypatch):
    monkeypatch.setattr(
        deps.shutil,
        "which",
        lambda name: None if name == "sudo" else "/usr/bin/apt-get",
    )
    with pytest.raises(
        RuntimeError, match="python_venv_package_unavailable: python3.12-venv"
    ):
        deps.ensure_venv_support(emit=lambda _: None)
    assert len(setup) == 1


def test_apt_failure_names_package_and_recovery(setup, monkeypatch):
    original = deps.subprocess.run

    def run(command, **kwargs):
        if "install" in command:
            return subprocess.CompletedProcess(command, 1, "", "apt lock held")
        return original(command, **kwargs)

    monkeypatch.setattr(deps.subprocess, "run", run)
    with pytest.raises(
        RuntimeError, match="python3.12-venv: apt lock held.*retry Yoke setup"
    ):
        deps.ensure_venv_support(emit=lambda _: None)


def test_successful_apt_must_supply_ensurepip(setup, monkeypatch):
    monkeypatch.setattr(deps, "_probe", lambda _: {"version": "3.12", "ready": False})
    with pytest.raises(
        RuntimeError, match="python_venv_missing_after_install: python3.12-venv"
    ):
        deps.ensure_venv_support(emit=lambda _: None)


def test_other_platforms_do_not_probe(setup, monkeypatch):
    monkeypatch.setattr(deps.sys, "platform", "darwin")
    deps.ensure_venv_support()
    assert setup == []


def test_relay_checks_stable_python_before_creating_release(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        relay, "ensure_venv_support", lambda python, **kw: calls.append(python)
    )

    def run(command, **kwargs):
        assert calls == [tmp_path / "stable-python"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(relay.subprocess, "run", run)
    relay.create_release_venv(tmp_path / "release", tmp_path / "stable-python")


def test_package_refusal_prevents_release_creation(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("python_venv_package_unavailable: python3.12-venv")

    monkeypatch.setattr(relay, "ensure_venv_support", refuse)
    monkeypatch.setattr(
        relay.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("release creation must not run"),
    )
    with pytest.raises(RuntimeError, match="python3.12-venv"):
        relay.create_release_venv(tmp_path / "release", tmp_path / "stable-python")

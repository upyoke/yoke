"""System-library setup privilege selection, diagnostics, and verification."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import browser_system_dependencies as deps
from yoke_harness import system_privileges as privileges


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(deps.sys, "platform", "linux")
    monkeypatch.setattr(privileges.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(deps.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(deps.sys, "stderr", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(deps.browser_linux_deps, "is_amazon_linux", lambda: False)
    monkeypatch.setattr(deps, "ensure_chromium_apparmor", lambda *args, **kwargs: None)
    toolchain = SimpleNamespace(node=tmp_path / "node")
    commands, logs = [], []
    probes = iter(["Missing libraries: libX11.so.6", ""])

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if "-e" in command:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"missing": next(probes)}), ""
            )
        if command[1:] == ["-n", "true"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(deps.subprocess, "run", run)

    def ensure():
        deps.ensure_system_dependencies(
            tmp_path, toolchain, env={"PATH": "/test"}, emit=logs.append
        )

    return ensure, commands, logs


def _install(commands):
    return next(
        (command, kwargs) for command, kwargs in commands if "install-deps" in command
    )


def test_root_invokes_playwright_package_installer_directly(setup, monkeypatch):
    ensure, commands, _ = setup
    monkeypatch.setattr(privileges.os, "geteuid", lambda: 0)
    ensure()
    command, _ = _install(commands)
    assert command[0].endswith("/node")
    assert not any("sudo" in command[0] for command, _ in commands)
    assert sum("-e" in command for command, _ in commands) == 2


def test_passwordless_sudo_is_noninteractive_and_rechecks(setup):
    ensure, commands, logs = setup
    ensure()
    command, kwargs = _install(commands)
    assert command[:3] == ["/usr/bin/sudo", "-n", "--"]
    assert kwargs["capture_output"] is True
    assert command[-2:] == ["install-deps", "chromium"]
    assert "verified" in logs[-1]


def test_interactive_sudo_inherits_terminal_for_one_password_prompt(setup, monkeypatch):
    ensure, commands, _ = setup
    original = deps.subprocess.run

    def run(command, **kwargs):
        if command[1:] == ["-n", "true"]:
            commands.append((command, kwargs))
            return subprocess.CompletedProcess(command, 1, "", "password required")
        return original(command, **kwargs)

    monkeypatch.setattr(deps.subprocess, "run", run)
    monkeypatch.setattr(deps.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(deps.sys, "stderr", SimpleNamespace(isatty=lambda: True))
    ensure()
    command, kwargs = _install(commands)
    assert command[:2] == ["/usr/bin/sudo", "--"]
    assert kwargs["capture_output"] is False
    assert sum("install-deps" in command for command, _ in commands) == 1
    assert "stdin" not in kwargs


@pytest.mark.parametrize("sudo_present", [True, False])
def test_no_install_authority_fails_fast_with_missing_libraries(
    setup, monkeypatch, sudo_present
):
    ensure, commands, _ = setup
    original = deps.subprocess.run

    def run(command, **kwargs):
        if command[1:] == ["-n", "true"]:
            return subprocess.CompletedProcess(command, 1, "", "password required")
        return original(command, **kwargs)

    monkeypatch.setattr(deps.subprocess, "run", run)
    if not sudo_present:
        monkeypatch.setattr(
            deps.shutil,
            "which",
            lambda name: None if name == "sudo" else "/usr/bin/" + name,
        )
    with pytest.raises(
        RuntimeError, match="browser_system_packages_unavailable"
    ) as failure:
        ensure()
    assert "libX11.so.6" in str(failure.value)
    assert "no way to install system packages" in str(failure.value)
    assert not any("install-deps" in command for command, _ in commands)


def test_present_libraries_need_no_privilege_probe(setup, monkeypatch):
    ensure, commands, _ = setup
    monkeypatch.setattr(deps, "_probe", lambda *args: {"missing": ""})
    ensure()
    assert commands == []


def test_present_libraries_still_provision_chromium_sandbox(setup, monkeypatch):
    ensure, _, _ = setup
    calls = []
    monkeypatch.setattr(deps, "_probe", lambda *args: {"missing": ""})
    monkeypatch.setattr(
        deps, "ensure_chromium_apparmor", lambda *args, **kwargs: calls.append(kwargs)
    )
    ensure()
    assert len(calls) == 1
    assert calls[0]["autoinstall"] is True


def test_missing_libraries_are_installed_before_sandbox_launch_probe(
    setup, monkeypatch
):
    ensure, commands, _ = setup

    def sandbox(*args, **kwargs):
        assert any("install-deps" in command for command, _ in commands)
        assert sum("-e" in command for command, _ in commands) == 2

    monkeypatch.setattr(deps, "ensure_chromium_apparmor", sandbox)
    ensure()


def test_failed_install_is_diagnosed_and_does_not_report_success(setup, monkeypatch):
    ensure, commands, logs = setup
    original = deps.subprocess.run
    monkeypatch.setattr(
        deps.subprocess,
        "run",
        lambda command, **kwargs: (
            subprocess.CompletedProcess(command, 1, "", "apt lock held")
            if "install-deps" in command
            else original(command, **kwargs)
        ),
    )
    with pytest.raises(
        RuntimeError, match="browser_system_package_install_failed.*apt lock held"
    ):
        ensure()
    assert not any("verified" in log for log in logs)


def test_install_success_still_requires_libraries_to_validate(setup, monkeypatch):
    ensure, _, _ = setup
    monkeypatch.setattr(deps, "_probe", lambda *args: {"missing": "libX11.so.6"})
    with pytest.raises(
        RuntimeError, match="browser_system_libraries_missing_after_install"
    ):
        ensure()


def test_amazon_linux_uses_the_existing_package_manager_adapter(setup, monkeypatch):
    ensure, commands, _ = setup
    monkeypatch.setattr(deps.browser_linux_deps, "is_amazon_linux", lambda: True)
    monkeypatch.setattr(
        deps.browser_linux_deps,
        "amazon_linux_chromium_deps_command",
        lambda: ["dnf", "install", "-y", "libX11"],
    )
    ensure()
    assert any(
        command == ["/usr/bin/sudo", "-n", "--", "dnf", "install", "-y", "libX11"]
        for command, _ in commands
    )


def test_probe_failure_never_triggers_package_install(setup, monkeypatch):
    ensure, commands, _ = setup
    monkeypatch.setattr(
        deps.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, "", "adapter unavailable"
        ),
    )
    with pytest.raises(
        RuntimeError, match="browser_dependency_check_failed.*adapter unavailable"
    ):
        ensure()
    assert commands == []

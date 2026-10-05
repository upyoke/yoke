"""Browser runtime Linux dependency installation contract."""

from __future__ import annotations

import subprocess

import pytest

from runtime.api.cli.browser_toolchain_test_support import (
    install_fake_toolchain,
)
from yoke_cli.browser_node_toolchain import NodeToolchainError
from yoke_harness import browser_client, browser_setup
from yoke_harness import browser_linux_deps
from yoke_harness.browser_linux_deps import AMAZON_LINUX_CHROMIUM_DEPS


def _prepare_browser_start(tmp_path, monkeypatch):
    browser = tmp_path / "browser"
    browser.joinpath("src").mkdir(parents=True)
    browser.joinpath("src", "daemon.js").write_text("", encoding="utf-8")
    browser.joinpath("node_modules", "playwright").mkdir(parents=True)

    monkeypatch.setattr(browser_client, "_browser_dir", lambda: browser)
    monkeypatch.setattr(
        browser_client,
        "_state_file_path",
        lambda profile_dir=None: tmp_path / "state.json",
    )
    monkeypatch.setattr(browser_client.sys, "platform", "linux")
    monkeypatch.setattr(browser_client.time, "sleep", lambda _seconds: None)

    loads = {"count": 0}

    def fake_load(path=None):
        loads["count"] += 1
        if loads["count"] == 1:
            return None
        return browser_client.DaemonState(
            pid=123,
            endpoint="http://127.0.0.1:9000",
            health="healthy",
        )

    def fake_run(command, **_kwargs):
        # The Chromium-presence probe is the only command whose output the
        # launch path reads; it answers "missing" so the install runs.
        if command[1:2] == ["-e"]:
            return subprocess.CompletedProcess(command, 0, "missing", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    class FakeProcess:
        pid = 123

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["node"], timeout)

        def kill(self):
            pass

    monkeypatch.setattr(browser_client.DaemonState, "load", staticmethod(fake_load))
    monkeypatch.setattr(
        browser_client,
        "daemon_request",
        lambda *_args, **_kwargs: {
            "success": True,
            "data": {"health": "healthy"},
        },
    )
    monkeypatch.setattr(
        browser_setup.subprocess, "Popen", lambda *args, **kwargs: FakeProcess()
    )
    toolchain = install_fake_toolchain(monkeypatch, tmp_path / "node-bin")
    return browser, fake_run, toolchain


def test_linux_download_is_user_space_then_shared_dependency_check(
    tmp_path, monkeypatch
):
    browser, base_fake_run, toolchain = _prepare_browser_start(tmp_path, monkeypatch)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return base_fake_run(command, **kwargs)

    monkeypatch.setattr(browser_setup.subprocess, "run", fake_run)
    monkeypatch.setattr(
        browser_setup,
        "ensure_system_dependencies",
        lambda *args, **kwargs: calls.append("dependencies"),
    )
    assert browser_client.daemon_start()["status"] == "started"
    install = [str(toolchain.npx), "playwright", "install", "chromium"]
    assert calls.index(install) < calls.index("dependencies")
    assert all("--with-deps" not in call for call in calls)


def test_existing_browser_still_checks_system_libraries(tmp_path, monkeypatch):
    browser, _, toolchain = _prepare_browser_start(tmp_path, monkeypatch)
    monkeypatch.setattr(
        browser_setup.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "ok", ""),
    )
    calls = []
    monkeypatch.setattr(
        browser_setup,
        "ensure_system_dependencies",
        lambda *args, **kwargs: calls.append(args),
    )
    browser_setup.ensure_browser_runtime(browser, toolchain)
    assert calls == [(browser, toolchain)]


def test_daemon_start_surfaces_the_toolchain_refusal(tmp_path, monkeypatch) -> None:
    """An unprovisionable Node reaches the caller as a named, actionable refusal."""
    browser = tmp_path / "browser"
    browser.joinpath("src").mkdir(parents=True)
    browser.joinpath("src", "daemon.js").write_text("", encoding="utf-8")
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: browser)
    monkeypatch.setattr(
        browser_client,
        "_state_file_path",
        lambda profile_dir=None: tmp_path / "state.json",
    )
    monkeypatch.setattr(
        browser_client.DaemonState,
        "load",
        staticmethod(lambda path=None: None),
    )
    refusal = NodeToolchainError(
        "the pinned Node.js release could not be fetched.",
        code="node_download_failed",
        recovery="confirm this host can reach nodejs.org/dist",
    )

    def refuse(*_args, **_kwargs):
        raise refusal

    monkeypatch.setattr(
        browser_client.browser_node_toolchain, "ensure_node_toolchain", refuse
    )

    with pytest.raises(NodeToolchainError) as raised:
        browser_client.daemon_start()

    assert raised.value.code == "node_download_failed"
    assert "nodejs.org/dist" in str(raised.value)


def test_amazon_linux_deps_command_names_dnf_when_packages_missing(monkeypatch) -> None:
    monkeypatch.setattr(browser_linux_deps, "_os_release_id", lambda: "amzn")
    monkeypatch.setattr(browser_linux_deps.sys, "platform", "linux")
    monkeypatch.setattr(
        browser_linux_deps.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"rpm", "dnf", "sudo"} else None,
    )
    monkeypatch.setattr(
        browser_linux_deps.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "", ""),
    )

    assert browser_linux_deps.amazon_linux_chromium_deps_command() == [
        "/usr/bin/dnf",
        "install",
        "-y",
        *AMAZON_LINUX_CHROMIUM_DEPS,
    ]


def test_amazon_linux_deps_command_skips_when_packages_installed(monkeypatch) -> None:
    monkeypatch.setattr(browser_linux_deps, "_os_release_id", lambda: "amzn")
    monkeypatch.setattr(browser_linux_deps.sys, "platform", "linux")
    monkeypatch.setattr(
        browser_linux_deps.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(
        browser_linux_deps.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )

    assert browser_linux_deps.amazon_linux_chromium_deps_command() == []

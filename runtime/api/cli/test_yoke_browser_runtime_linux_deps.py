"""Browser runtime Linux dependency installation contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_harness import browser_client
from yoke_harness import browser_linux_deps
from yoke_harness.browser_linux_deps import AMAZON_LINUX_CHROMIUM_DEPS


def _prepare_browser_start(tmp_path, monkeypatch):
    browser = tmp_path / "browser"
    browser.joinpath("src").mkdir(parents=True)
    browser.joinpath("src", "daemon.js").write_text("", encoding="utf-8")
    browser.joinpath("node_modules", "playwright").mkdir(parents=True)

    monkeypatch.setattr(browser_client, "_browser_dir", lambda: browser)
    monkeypatch.setattr(browser_client, "_state_file_path", lambda: tmp_path / "state.json")
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
        if command[:2] == ["which", "node"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["node", "-e"]:
            return subprocess.CompletedProcess(command, 0, "missing", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    class FakeProcess:
        pid = 123

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["node"], timeout)

        def kill(self):
            pass

    monkeypatch.setattr(browser_client.DaemonState, "load", staticmethod(fake_load))
    monkeypatch.setattr(browser_client.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    return browser, fake_run


def test_linux_chromium_install_asks_playwright_for_os_deps(tmp_path, monkeypatch) -> None:
    _browser, base_fake_run = _prepare_browser_start(tmp_path, monkeypatch)
    commands: list[list[str]] = []
    monkeypatch.setattr(browser_client, "is_amazon_linux", lambda: False)
    monkeypatch.setattr(browser_client, "amazon_linux_chromium_deps_command", lambda: [])

    def fake_run(command, **kwargs):
        commands.append(list(command))
        return base_fake_run(command, **kwargs)

    monkeypatch.setattr(browser_client.subprocess, "run", fake_run)

    assert browser_client.daemon_start() == {
        "status": "started",
        "endpoint": "http://127.0.0.1:9000",
        "pid": 123,
    }
    assert ["npx", "playwright", "install", "--with-deps", "chromium"] in commands


def test_amazon_linux_installs_dnf_deps_before_chromium(tmp_path, monkeypatch) -> None:
    _browser, base_fake_run = _prepare_browser_start(tmp_path, monkeypatch)
    commands: list[list[str]] = []
    deps = ["sudo", "dnf", "install", "-y", *AMAZON_LINUX_CHROMIUM_DEPS]
    monkeypatch.setattr(browser_client, "is_amazon_linux", lambda: True)
    monkeypatch.setattr(browser_client, "amazon_linux_chromium_deps_command", lambda: deps)

    def fake_run(command, **kwargs):
        commands.append(list(command))
        return base_fake_run(command, **kwargs)

    monkeypatch.setattr(browser_client.subprocess, "run", fake_run)

    assert browser_client.daemon_start()["status"] == "started"
    assert deps in commands
    assert ["npx", "playwright", "install", "chromium"] in commands
    assert ["npx", "playwright", "install", "--with-deps", "chromium"] not in commands


def test_amazon_linux_deps_command_uses_sudo_dnf_when_packages_missing(monkeypatch) -> None:
    monkeypatch.setattr(browser_linux_deps, "_os_release_id", lambda: "amzn")
    monkeypatch.setattr(browser_linux_deps.sys, "platform", "linux")
    monkeypatch.setattr(browser_linux_deps.os, "geteuid", lambda: 1000)
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
        "sudo",
        "/usr/bin/dnf",
        "install",
        "-y",
        *AMAZON_LINUX_CHROMIUM_DEPS,
    ]


def test_amazon_linux_deps_command_skips_when_packages_installed(monkeypatch) -> None:
    monkeypatch.setattr(browser_linux_deps, "_os_release_id", lambda: "amzn")
    monkeypatch.setattr(browser_linux_deps.sys, "platform", "linux")
    monkeypatch.setattr(browser_linux_deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        browser_linux_deps.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )

    assert browser_linux_deps.amazon_linux_chromium_deps_command() == []

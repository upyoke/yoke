"""Shared fake Node toolchain for browser daemon-launch tests."""

from __future__ import annotations

import subprocess

from yoke_harness import browser_client, browser_setup

from pathlib import Path

from yoke_cli import browser_node_toolchain
from yoke_cli.browser_node_toolchain import NodeToolchain


def install_fake_toolchain(monkeypatch, bin_dir: Path) -> NodeToolchain:
    """Pin daemon launches to a known toolchain instead of the host's Node.

    The launch path spawns node, npm, and npx by absolute path, so a test that
    asserts which commands it ran has to know those paths. Leaving resolution
    to the host would make the assertions depend on whichever Node the machine
    running the suite happens to carry — or on it carrying one at all.
    """
    toolchain = NodeToolchain(bin_dir=bin_dir, version="v24.20.0", source="managed")
    monkeypatch.setattr(
        browser_node_toolchain,
        "ensure_node_toolchain",
        lambda *_args, **_kwargs: toolchain,
    )
    return toolchain


__all__ = ["install_fake_toolchain"]


def stub_profile_daemon_start(monkeypatch, tmp_path, state_loads):
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
    monkeypatch.setattr(browser_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        browser_setup, "ensure_system_dependencies", lambda *args, **kwargs: None
    )

    loads = {"count": 0}

    def fake_load(path=None):
        index = min(loads["count"], len(state_loads) - 1)
        loads["count"] += 1
        return state_loads[index]

    monkeypatch.setattr(browser_client.DaemonState, "load", staticmethod(fake_load))
    monkeypatch.setattr(
        browser_client,
        "daemon_request",
        lambda *_args, **_kwargs: {"success": True, "data": {"health": "healthy"}},
    )
    monkeypatch.setattr(
        browser_setup.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            "ok" if command[1:2] == ["-e"] else "",
            "",
        ),
    )

    launched: list[list[str]] = []

    class FakeProcess:
        pid = 4242

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["node"], timeout)

        def kill(self):
            pass

    def fake_popen(command, **_kwargs):
        launched.append(list(command))
        return FakeProcess()

    monkeypatch.setattr(browser_setup.subprocess, "Popen", fake_popen)
    install_fake_toolchain(monkeypatch, tmp_path / "node-bin")
    return launched

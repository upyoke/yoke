"""Approval links use a real desktop browser or QA's reusable Chromium install."""

from __future__ import annotations

import io
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.config import hosted_machine_browser as browser
from yoke_cli.config import onboard_browser_runtime as runtime

URL = "https://example.invalid/connect?user_code=ABCD&other=value"
DESKTOP = {"DISPLAY": ":0"}


@pytest.fixture(autouse=True)
def no_wsl(monkeypatch):
    monkeypatch.setattr(browser.platform_info, "release", lambda: "Linux")


def test_default_browser_is_used_before_the_runtime(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "default_browser_command", lambda _: ["firefox"])
    monkeypatch.setattr(
        runtime, "open_system_browser", lambda *args: calls.append(args)
    )
    monkeypatch.setattr(
        runtime, "open_runtime_browser", lambda _: pytest.fail("download")
    )
    result = browser.open_url(URL, platform="linux", environ=DESKTOP)
    assert result.opened and result.method == "system-browser"
    assert calls == [(["firefox"], URL, DESKTOP)]


def test_async_desktop_launcher_is_not_trusted_without_a_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "default_browser_command", lambda _: None)
    monkeypatch.setattr(browser.webbrowser, "open", lambda _: pytest.fail("xdg-open"))
    monkeypatch.setattr(runtime, "open_runtime_browser", lambda url: calls.append(url))
    result = browser.open_url(URL, platform="linux", environ=DESKTOP)
    assert result.opened and result.method == "yoke-chromium"
    assert calls == [URL]


def test_headless_never_attempts_open_or_install(monkeypatch):
    monkeypatch.setattr(
        runtime, "default_browser_command", lambda _: pytest.fail("probe")
    )
    monkeypatch.setattr(
        runtime, "open_runtime_browser", lambda _: pytest.fail("download")
    )
    result = browser.open_url(URL, platform="linux", environ={"SSH_TTY": "/dev/pts/0"})
    assert not result.opened and result.reason == "browser_display_unavailable"


@pytest.mark.parametrize("system_present", [False, True])
def test_failed_open_is_an_honest_failure(monkeypatch, system_present):
    def fail(*_args):
        raise RuntimeError("cannot start browser")

    monkeypatch.setattr(
        runtime,
        "default_browser_command",
        lambda _: ["firefox"] if system_present else None,
    )
    monkeypatch.setattr(runtime, "open_system_browser", fail)
    monkeypatch.setattr(runtime, "open_runtime_browser", fail)
    result = browser.open_url(URL, platform="linux", environ=DESKTOP)
    assert not result.opened
    assert "cannot start browser" in result.reason


@pytest.mark.parametrize("installed", [False, True])
def test_runtime_uses_the_qa_installer_and_reuses_its_cache(
    monkeypatch, tmp_path, installed
):
    home = tmp_path / "browser-runtime"
    home.mkdir()
    modules = home / "node_modules/playwright"
    if installed:
        modules.mkdir(parents=True)
    toolchain = SimpleNamespace(
        node=Path("/bin/node"),
        npm=Path("/bin/npm"),
        npx=Path("/bin/npx"),
        command_env=lambda: {"PLAYWRIGHT_BROWSERS_PATH": "shared-cache"},
    )
    monkeypatch.setattr(
        runtime.browser_runtime_home, "ensure_materialized", lambda: home
    )
    monkeypatch.setattr(
        runtime.browser_node_toolchain, "ensure_node_toolchain", lambda: toolchain
    )
    monkeypatch.setattr(
        runtime.browser_setup, "ensure_system_dependencies", lambda *a, **k: None
    )
    calls = []
    present = installed

    def run(argv, **kwargs):
        nonlocal present
        calls.append(argv)
        assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == "shared-cache"
        if argv[1:] == ["install"]:
            modules.mkdir(parents=True)
        if argv[1:] == ["playwright", "install", "chromium"]:
            present = True
        return subprocess.CompletedProcess(argv, 0, "ok" if present else "missing", "")

    monkeypatch.setattr(runtime.browser_setup.subprocess, "run", run)
    launches = []
    process = SimpleNamespace(stdout=io.StringIO('{"opened":true}\n'))

    def launch(argv, **kwargs):
        launches.append(argv)
        assert kwargs["cwd"] == home
        assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == "shared-cache"
        return process

    monkeypatch.setattr(runtime.subprocess, "Popen", launch)
    monkeypatch.setattr(runtime.select, "select", lambda *a: ([process.stdout], [], []))
    runtime.open_runtime_browser(URL)
    first = list(calls)
    # Browser QA invokes exactly this setup path on the same machine home.
    runtime.browser_setup.ensure_browser_runtime(home, toolchain, emit=lambda _: None)
    assert len(
        [c for c in calls if c[1:] == ["playwright", "install", "chromium"]]
    ) == (0 if installed else 1)
    assert len([c for c in calls if c[1:] == ["install"]]) == (0 if installed else 1)
    assert all(c[1] == "-e" for c in calls[len(first) :])
    assert launches[0][-1] == URL


def test_stale_desktop_association_is_not_a_browser(monkeypatch, tmp_path):
    apps = tmp_path / "applications"
    apps.mkdir()
    entry = apps / "firefox.desktop"
    entry.write_text("[Desktop Entry]\nExec=firefox %u\n")
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "firefox.desktop\n", ""),
    )
    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda name, **k: "/usr/bin/xdg-settings" if name == "xdg-settings" else None,
    )
    assert runtime.default_browser_command({"XDG_DATA_HOME": str(tmp_path)}) is None
    monkeypatch.setattr(runtime.shutil, "which", lambda name, **k: "/usr/bin/" + name)
    assert runtime.default_browser_command({"XDG_DATA_HOME": str(tmp_path)}) == [
        "firefox"
    ]


def test_chromium_failure_requires_an_acknowledgement(monkeypatch, tmp_path):
    monkeypatch.setattr(
        runtime.browser_runtime_home, "ensure_materialized", lambda: tmp_path
    )
    monkeypatch.setattr(
        runtime.browser_node_toolchain,
        "ensure_node_toolchain",
        lambda: SimpleNamespace(node="node"),
    )
    monkeypatch.setattr(
        runtime.browser_setup, "ensure_browser_runtime", lambda *a, **k: {}
    )
    process = SimpleNamespace(
        stdout=io.StringIO('{"error":"missing display library"}\n'),
        poll=lambda: 1,
        wait=lambda **k: 1,
    )
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(runtime.select, "select", lambda *a: ([process.stdout], [], []))
    with pytest.raises(RuntimeError, match="missing display library"):
        runtime.open_runtime_browser(URL)


def test_xfce_browser_launcher_is_not_an_installed_browser(monkeypatch, tmp_path):
    apps = tmp_path / "applications"
    apps.mkdir()
    (apps / "exo-web-browser.desktop").write_text(
        "[Desktop Entry]\nExec=exo-open --launch WebBrowser %u\n"
    )
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, "exo-web-browser.desktop\n", ""
        ),
    )
    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda name, **k: None if name == "x-www-browser" else "/usr/bin/" + name,
    )
    assert runtime.default_browser_command({"XDG_DATA_HOME": str(tmp_path)}) is None


def test_system_browser_start_failure_is_not_reported_open(monkeypatch):
    monkeypatch.setattr(
        runtime.subprocess,
        "Popen",
        lambda *a, **k: SimpleNamespace(wait=lambda **k: 127),
    )
    with pytest.raises(RuntimeError, match="browser exited 127"):
        runtime.open_system_browser(["firefox"], URL, DESKTOP)

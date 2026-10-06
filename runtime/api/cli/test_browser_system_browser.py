"""Blocked bundle downloads select only a proven installed Chromium."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.config import browser_executable
from yoke_harness import browser_setup, browser_system_browser as system


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    root = tmp_path / "runtime"
    (root / "node_modules/playwright").mkdir(parents=True)
    executable = tmp_path / "chromium"
    executable.write_text("test executable")
    toolchain = SimpleNamespace(
        node=Path("node"),
        npm=Path("npm"),
        npx=Path("npx"),
        command_env=lambda: {browser_executable.EXECUTABLE_ENV: "untrusted-ambient"},
    )
    monkeypatch.setattr(
        browser_setup, "resolve_playwright_cache", lambda *a: str(tmp_path / "cache")
    )
    monkeypatch.setattr(system, "candidates", lambda saved=None: [str(executable)])
    monkeypatch.setattr(
        browser_setup,
        "ensure_system_dependencies",
        lambda *a, **k: pytest.fail("bundled dependencies"),
    )
    return root, toolchain, executable, config


def test_browser_setup_secures_the_machine_home_before_persisting(runtime, monkeypatch):
    root, toolchain, executable, config = runtime
    config.parent.chmod(0o755)
    monkeypatch.setattr(
        browser_setup.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(
            command,
            0 if command[-1] == str(executable) else 1,
            "ok" if command[-1] == str(executable) else "<html>Site Unavailable</html>",
            "",
        ),
    )
    browser_setup.ensure_browser_runtime(root, toolchain, emit=lambda _: None)
    assert config.parent.stat().st_mode & 0o777 == 0o700
    assert browser_executable.configured() == str(executable)


def test_blocked_download_saves_only_after_real_test_page_probe(runtime, monkeypatch):
    root, toolchain, executable, config = runtime
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert browser_executable.EXECUTABLE_ENV not in kwargs["env"]
        if command[1:2] == ["playwright"]:
            return subprocess.CompletedProcess(
                command, 1, "<html>Site Unavailable</html>", "openresty"
            )
        if command[-1] == str(executable):
            assert command[2] == system.LAUNCH_PROBE_JS
            assert not config.exists()
            return subprocess.CompletedProcess(command, 0, "ok", "")
        return subprocess.CompletedProcess(command, 0, "missing", "")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    env = browser_setup.ensure_browser_runtime(root, toolchain, emit=lambda _: None)
    assert env[browser_executable.EXECUTABLE_ENV] == str(executable)
    assert json.loads(config.read_text())["settings"][
        browser_executable.SETTING_KEY
    ] == str(executable)
    calls.clear()

    def reuse(command, **kwargs):
        calls.append(command)
        assert command[1] == "-e", "saved browser must not download again"
        return subprocess.CompletedProcess(
            command, 0, "ok" if command[-1] == str(executable) else "missing", ""
        )

    monkeypatch.setattr(browser_setup.subprocess, "run", reuse)
    assert browser_setup.ensure_browser_runtime(root, toolchain, emit=lambda _: None)[
        browser_executable.EXECUTABLE_ENV
    ] == str(executable)
    assert len(calls) == 2


def test_failed_system_launch_does_not_save_path_and_names_blocked_hosts(
    runtime, monkeypatch
):
    root, toolchain, executable, config = runtime

    def run(command, **kwargs):
        if command[1:2] == ["playwright"]:
            return subprocess.CompletedProcess(
                command, 1, "<html>Site Unavailable</html>", ""
            )
        if command[-1] == str(executable):
            return subprocess.CompletedProcess(command, 1, "", "sandbox launch refused")
        return subprocess.CompletedProcess(command, 0, "missing", "")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="browser_download_blocked") as error:
        browser_setup.ensure_browser_runtime(root, toolchain, emit=lambda _: None)
    assert "HTML block page" in str(error.value)
    for host in (
        "cdn.playwright.dev",
        "playwright.download.prss.microsoft.com",
        "playwright.azureedge.net",
    ):
        assert host in str(error.value)
    assert not config.exists()


def test_bundled_browser_is_preferred_and_clears_saved_selection(runtime, monkeypatch):
    root, toolchain, executable, _ = runtime
    browser_executable.save(str(executable))
    monkeypatch.setattr(
        browser_setup.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(command, 0, "ok", ""),
    )
    monkeypatch.setattr(
        browser_setup, "ensure_system_dependencies", lambda *a, **k: None
    )
    env = browser_setup.ensure_browser_runtime(root, toolchain, emit=lambda _: None)
    assert browser_executable.EXECUTABLE_ENV not in env
    assert browser_executable.configured() is None

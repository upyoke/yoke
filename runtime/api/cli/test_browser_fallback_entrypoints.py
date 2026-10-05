"""Browser entrypoints consume the executable selected by real setup routing."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_cli.config import browser_executable, browser_profile
from yoke_cli.commands import browser_authorize, qa_browser_lifecycle
from yoke_core.domain import browser_client, browser_client_lifecycle
from yoke_harness import browser_runtime_home, browser_setup, browser_system_browser


@pytest.fixture
def fallback(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config))
    monkeypatch.setenv("YOKE_BROWSER_AUTOINSTALL", "1")
    root = tmp_path / "runtime"
    (root / "node_modules/playwright").mkdir(parents=True)
    (root / "src").mkdir()
    for name in ("authorize.js", "daemon.js"):
        (root / "src" / name).write_text("")
    executable = tmp_path / "chromium"
    executable.write_text("fixture browser")
    toolchain = SimpleNamespace(
        node="node", npm="npm", npx="npx", command_env=lambda: {"DISPLAY": ":10"}
    )
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:2] == ["playwright"]:
            return subprocess.CompletedProcess(command, 1, "<html>Site Unavailable", "")
        if command[-1] == str(executable):
            assert command[2] == browser_system_browser.LAUNCH_PROBE_JS
            return subprocess.CompletedProcess(command, 0, "ok", "")
        if command[1] == str(root / "src/authorize.js"):
            assert browser_executable.configured() == str(executable)
            assert kwargs["env"][browser_executable.EXECUTABLE_ENV] == str(executable)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "missing", "")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    monkeypatch.setattr(
        browser_system_browser, "candidates", lambda saved=None: [str(executable)]
    )
    monkeypatch.setattr(
        browser_setup,
        "ensure_system_dependencies",
        lambda *a, **k: pytest.fail("bundled dependencies"),
    )
    monkeypatch.setattr(browser_runtime_home, "ensure_materialized", lambda: root)
    monkeypatch.setattr(
        browser_authorize.browser_node_toolchain,
        "ensure_node_toolchain",
        lambda **k: toolchain,
    )
    monkeypatch.setattr(
        browser_authorize.browser_node_toolchain,
        "resolve_node_toolchain",
        lambda: toolchain,
    )
    return root, toolchain, executable, config, calls


def test_authorize_preserves_setup_selected_environment(fallback, monkeypatch, capsys):
    root, _, executable, config, calls = fallback
    monkeypatch.setattr(
        browser_profile, "profile_project_key", lambda *a, **k: "fixture"
    )
    monkeypatch.setattr(
        browser_profile, "ensure_profile_dir", lambda *a: root / "profile"
    )
    monkeypatch.setattr(
        browser_authorize, "_stop_daemon_holding_profile", lambda *a: None
    )
    monkeypatch.setattr(browser_authorize, "keep_sign_in_cookies", lambda *a: 0)
    assert not config.exists()
    assert browser_authorize.browser_authorize(["--project", "fixture", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert browser_executable.configured() == str(executable)
    environment = calls[-1][1]["env"]
    assert environment["DISPLAY"] == ":10"
    assert environment["PLAYWRIGHT_BROWSERS_PATH"]


def test_status_proves_the_saved_selection_without_mutating_it(fallback):
    root, toolchain, executable, config, calls = fallback
    browser_setup.ensure_browser_runtime(root, toolchain, emit=lambda _: None)
    before = config.read_bytes()
    calls.clear()
    assert qa_browser_lifecycle._chromium_status(root) == "ready"
    assert len(calls) == 1 and calls[0][0][-1] == str(executable)
    assert config.read_bytes() == before


def test_status_refuses_a_selection_that_cannot_launch(fallback, monkeypatch):
    root, toolchain, _, config, _ = fallback
    browser_setup.ensure_browser_runtime(root, toolchain, emit=lambda _: None)
    before = config.read_bytes()
    monkeypatch.setattr(
        browser_setup.subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "sandbox refused"),
    )
    assert qa_browser_lifecycle._chromium_status(root) == "missing"
    assert config.read_bytes() == before


def test_core_daemon_bootstrap_uses_the_shared_fallback_resolution(
    fallback, monkeypatch
):
    root, _, executable, config, _ = fallback
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: root)
    monkeypatch.setattr(
        browser_client, "_state_file_path", lambda *a: root / "state.json"
    )
    monkeypatch.setattr(browser_client.DaemonState, "load", lambda *a: None)
    launches = []

    def start(command, env, directory, **kwargs):
        launches.append((command, env))
        return {"status": "started"}

    from yoke_harness import browser_client_readiness

    monkeypatch.setattr(browser_client_readiness, "start_daemon", start)
    assert not config.exists()
    assert browser_client_lifecycle.daemon_start()["status"] == "started"
    assert browser_executable.configured() == str(executable)
    assert launches[0][1][browser_executable.EXECUTABLE_ENV] == str(executable)
    assert launches[0][0][:2] == ["node", str(root / "src/daemon.js")]

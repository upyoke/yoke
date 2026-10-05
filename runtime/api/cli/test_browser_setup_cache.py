"""Browser setup uses the runtime cache and keeps install failure evidence."""

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.playwright_cache import (
    YOKE_BROWSER_CACHE_PROJECT,
    resolve_playwright_cache,
)
from yoke_harness import browser_setup


@pytest.fixture
def setup_host(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("YOKE_BROWSER_AUTOINSTALL", "1")
    browser = tmp_path / "browser"
    browser.mkdir()
    toolchain = SimpleNamespace(
        node="node",
        npm="npm",
        npx="npx",
        command_env=lambda: dict(browser_setup.os.environ),
    )
    monkeypatch.setattr(
        browser_setup, "ensure_system_dependencies", lambda *a, **k: None
    )
    return browser, toolchain


@pytest.mark.parametrize("command", ["npm", "npx"])
def test_install_failure_preserves_warning_and_download_error(
    setup_host, monkeypatch, command
):
    browser, toolchain = setup_host
    if command == "npx":
        (browser / "node_modules/playwright").mkdir(parents=True)

    def run(argv, **kwargs):
        if argv[0] == command:
            return subprocess.CompletedProcess(
                argv,
                1,
                "Failed to install browsers\n"
                "End of central directory record signature not found",
                'npm warn Unknown env config "http-proxy"',
            )
        return subprocess.CompletedProcess(argv, 0, "missing", "")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    with pytest.raises(RuntimeError) as failure:
        browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    message = str(failure.value)
    assert (
        f"browser_{'npm_install' if command == 'npm' else 'install'}_failed" in message
    )
    assert "exit 1" in message
    assert "stdout (last 20 lines" in message
    assert "stderr (last 20 lines" in message
    assert "End of central directory record signature not found" in message
    assert 'npm warn Unknown env config "http-proxy"' in message
    assert "retry yoke qa browser setup" in message


def test_command_output_is_bounded_per_stream():
    result = subprocess.CompletedProcess(
        [],
        1,
        "discard-stdout\n" * 30 + "stdout-tail\n",
        "discard-stderr\n" * 30 + "x" * 10000 + "stderr-tail\n",
    )
    output = browser_setup._command_output_tail(result)
    stdout, stderr = output.split("stderr (last 20 lines, at most 4000 characters):\n")
    assert stdout.count("discard-stdout") == 19
    assert "discard-stderr" not in stderr
    assert len(stderr) == 4000
    assert output.endswith("stderr-tail")
    assert "stdout-tail" in output


@pytest.mark.parametrize("xdg_uncreatable", [False, True])
def test_setup_install_and_runtime_find_the_same_cache(
    setup_host, tmp_path, monkeypatch, xdg_uncreatable
):
    from yoke_cli import browser_node_toolchain
    from yoke_core.domain import browser_client, browser_client_lifecycle, worktree_deps
    from yoke_harness import browser_client_readiness

    browser, toolchain = setup_host
    (browser / "node_modules/playwright").mkdir(parents=True)
    (browser / "src").mkdir()
    (browser / "src/daemon.js").write_text("")
    if xdg_uncreatable:
        blocked_parent = tmp_path / "blocked"
        blocked_parent.write_text("not a directory")
        monkeypatch.setenv("XDG_CACHE_HOME", str(blocked_parent / "cache"))
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "other-cache"))
    cache = Path(resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None))
    assert worktree_deps.resolve_playwright_cache is resolve_playwright_cache
    installed = cache / "chromium"
    installs = []

    def run(argv, **kwargs):
        assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(cache)
        if argv[0] == "npx":
            installs.append(argv)
            installed.write_text("browser")
        return subprocess.CompletedProcess(
            argv, 0, "ok" if installed.exists() else "missing", ""
        )

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    env = browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(cache)
    assert installed.is_file()
    monkeypatch.setattr(browser_client.DaemonState, "load", lambda: None)
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: browser)
    monkeypatch.setattr(
        browser_client, "_state_file_path", lambda: tmp_path / "state.json"
    )
    monkeypatch.setattr(
        browser_node_toolchain, "ensure_node_toolchain", lambda **k: toolchain
    )

    def start(cmd, env, browser, **kwargs):
        assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(cache)
        assert installed.is_file()
        return {"status": "started"}

    monkeypatch.setattr(browser_client_readiness, "start_daemon", start)
    assert browser_client_lifecycle.daemon_start()["status"] == "started"
    assert len(installs) == 1


@pytest.mark.parametrize("failure_at", ["mkdir", "open", "write"])
def test_cache_writability_refuses_before_install(setup_host, monkeypatch, failure_at):
    browser, toolchain = setup_host
    cache = resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None)

    def refuse(*args, **kwargs):
        raise PermissionError("write denied")

    if failure_at == "mkdir":
        monkeypatch.setattr(Path, "mkdir", refuse)
    elif failure_at == "open":
        monkeypatch.setattr(browser_setup.tempfile, "TemporaryFile", refuse)
    else:

        class UnwritableFile:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            write = refuse

        monkeypatch.setattr(
            browser_setup.tempfile, "TemporaryFile", lambda **k: UnwritableFile()
        )
    monkeypatch.setattr(
        browser_setup.subprocess, "run", lambda *a, **k: pytest.fail("install ran")
    )
    with pytest.raises(RuntimeError, match="browser_cache_not_writable") as failure:
        browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    assert cache in str(failure.value)
    assert "make this directory and its parents writable" in str(failure.value)
    assert "retry yoke qa browser setup" in str(failure.value)

"""Browser setup uses the runtime cache and keeps install failure evidence."""

from yoke_contracts.testing.real_home_isolation import set_home

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_contracts.playwright_cache import (
    YOKE_BROWSER_CACHE_PROJECT,
    resolve_playwright_cache,
)
from yoke_harness import browser_setup


@pytest.fixture
def setup_host(tmp_path, monkeypatch):
    set_home(monkeypatch, str(tmp_path))
    monkeypatch.setenv("YOKE_BROWSER_AUTOINSTALL", "1")
    browser = tmp_path / "browser"
    browser.mkdir()
    toolchain = SimpleNamespace(
        node="node",
        npm="npm",
        npx="npx",
        package_command=lambda name, *args: [name, *args],
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
        loaded = command != "npm" and argv[-1] == browser_setup.PLAYWRIGHT_LOAD_PROBE_JS
        return subprocess.CompletedProcess(argv, 0, "ok" if loaded else "missing", "")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    with pytest.raises(RuntimeError) as failure:
        browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    message = str(failure.value)
    assert (
        "browser_npm_install_failed" if command == "npm" else "browser_download_blocked"
    ) in message
    if command == "npx":
        assert "playwright.download.prss.microsoft.com" in message
    assert "exit 1" in message
    assert "stdout (last 20 lines" in message
    assert "stderr (last 20 lines" in message
    assert "End of central directory record signature not found" in message
    assert 'npm warn Unknown env config "http-proxy"' in message
    assert "retry yoke qa browser setup" in message


def test_restricted_userns_without_root_finishes_setup_with_sandbox_off(
    setup_host, monkeypatch
):
    browser, toolchain = setup_host
    (browser / "node_modules/playwright").mkdir(parents=True)

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    monkeypatch.setattr(
        browser_setup, "ensure_system_dependencies", lambda *args, **kwargs: False
    )
    env = browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    assert env["YOKE_BROWSER_CHROMIUM_SANDBOX"] == "0"


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
        if argv[-1] == browser_setup.PLAYWRIGHT_LOAD_PROBE_JS:
            return subprocess.CompletedProcess(argv, 0, "ok", "")
        return subprocess.CompletedProcess(
            argv, 0, "ok" if installed.exists() else "missing", ""
        )

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    env = browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(cache)
    assert installed.is_file()
    monkeypatch.setattr(browser_client.DaemonState, "load", lambda path=None: None)
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: browser)
    monkeypatch.setattr(
        browser_client,
        "_state_file_path",
        lambda profile_dir=None: tmp_path / "state.json",
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
        mkdir = Path.mkdir

        def refuse_cache(path, *args, **kwargs):
            if str(path) == cache:
                refuse()
            return mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", refuse_cache)
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


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_partial_playwright_is_rechecked_before_chromium(
    setup_host, monkeypatch, repair_succeeds
):
    browser, toolchain = setup_host
    package = browser / "node_modules/playwright/package.json"
    package.parent.mkdir(parents=True)
    calls = []

    def run(argv, **kwargs):
        command = argv[0] if argv[0] == "npm" else argv[2]
        calls.append(command)
        if command == "npm":
            if repair_succeeds:
                package.write_text("{}")
        elif command == browser_setup.PLAYWRIGHT_LOAD_PROBE_JS:
            assert kwargs["timeout"] == browser_setup.PLAYWRIGHT_PROBE_TIMEOUT_SECONDS
            if not package.exists():
                return subprocess.CompletedProcess(
                    argv, 1, "", "Cannot find module './node_modules/playwright'"
                )
        else:
            assert package.exists(), "Chromium ran before Playwright was repaired"
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    if repair_succeeds:
        browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
        assert "npx" not in calls
    else:
        with pytest.raises(
            RuntimeError, match="browser_playwright_unloadable_after_install"
        ) as failure:
            browser_setup.ensure_browser_runtime(
                browser, toolchain, emit=lambda _: None
            )
        assert "Cannot find module './node_modules/playwright'" in str(failure.value)
        assert "retry yoke qa browser setup" in str(failure.value)
        assert len(calls) == 3
    assert calls[:3] == [
        browser_setup.PLAYWRIGHT_LOAD_PROBE_JS,
        "npm",
        browser_setup.PLAYWRIGHT_LOAD_PROBE_JS,
    ]


@pytest.mark.parametrize("executable_present", [False, True])
def test_installer_success_requires_usable_chromium(
    setup_host, monkeypatch, executable_present
):
    browser, toolchain = setup_host
    installed = False
    events = []

    def run(argv, **kwargs):
        nonlocal installed
        if argv[0] == "npx":
            installed = True
        elif argv[-1] == browser_setup.browser_runtime_home.CHROMIUM_PRESENT_PROBE_JS:
            if not (installed and executable_present):
                return subprocess.CompletedProcess(argv, 1, "", "Chromium file missing")
        elif argv[2] == browser_setup.browser_system_browser.LAUNCH_PROBE_JS:
            return subprocess.CompletedProcess(
                argv, 1, "", "Chromium exec format error"
            )
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    with pytest.raises(
        RuntimeError, match="browser_chromium_unusable_after_install"
    ) as failure:
        browser_setup.ensure_browser_runtime(browser, toolchain, emit=events.append)
    expected = (
        "Chromium exec format error" if executable_present else "Chromium file missing"
    )
    assert expected in str(failure.value)
    assert "retry yoke qa browser setup" in str(failure.value)
    assert not any("installation verified" in event for event in events)


def test_npm_failure_preserves_diagnostics_with_malformed_bytes(
    setup_host, monkeypatch
):
    browser, toolchain = setup_host
    real_run = subprocess.run

    def run(argv, **kwargs):
        if argv[0] == "npm":
            return real_run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.buffer.write(b'first \\xff final diagnostic'); sys.exit(1)",
                ],
                **kwargs,
            )
        return subprocess.CompletedProcess(argv, 1, "", "module missing")

    monkeypatch.setattr(browser_setup.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="browser_npm_install_failed") as failure:
        browser_setup.ensure_browser_runtime(browser, toolchain, emit=lambda _: None)
    assert "first � final diagnostic" in str(failure.value)

"""One browser installation path for onboarding and daemon startup."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from yoke_cli import browser_node_toolchain
from yoke_contracts import terminal_detached_process
from yoke_cli.config import browser_executable
from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config.machine_config_file import ensure_owner_only_directory
from yoke_contracts.playwright_cache import (
    YOKE_BROWSER_CACHE_PROJECT,
    resolve_playwright_cache,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_harness import browser_runtime_home
from yoke_harness import browser_system_browser
from yoke_harness.browser_apparmor import SANDBOX_ENV
from yoke_harness.browser_system_dependencies import ensure_system_dependencies

NPM_INSTALL_TIMEOUT_SECONDS = 180
PLAYWRIGHT_PROBE_TIMEOUT_SECONDS = 15
CHROMIUM_PROBE_TIMEOUT_SECONDS = 40
CHROMIUM_INSTALL_TIMEOUT_SECONDS = 300
PLAYWRIGHT_LOAD_PROBE_JS = (
    "const { chromium } = require('./node_modules/playwright'); "
    "if (typeof chromium?.launch !== 'function') throw new Error('Playwright has no Chromium launcher'); "
    "process.stdout.write('ok');"
)


def _run_setup_command(argv, *, timeout: int, reason: str, **kwargs):
    try:
        return terminal_detached_process.run(argv, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{reason}: exceeded {timeout} seconds. Check network access and "
            "runtime permissions, then retry yoke qa browser setup."
        ) from exc


def _command_output_tail(result: subprocess.CompletedProcess) -> str:
    return "\n".join(
        f"{label} (last 20 lines, at most 4000 characters):\n"
        + ("\n".join((output or "").splitlines()[-20:])[-4000:] or "<empty>")
        for label, output in (("stdout", result.stdout), ("stderr", result.stderr))
    )


def _probe_passed(result: subprocess.CompletedProcess) -> bool:
    return result.returncode == 0 and result.stdout.strip() == "ok"


def playwright_load_error(browser: Path, toolchain, *, env=None) -> str | None:
    """Return a bounded load diagnostic, or None for the packaged module."""
    try:
        result = terminal_detached_process.run(
            [str(toolchain.node), "-e", PLAYWRIGHT_LOAD_PROBE_JS],
            cwd=str(browser),
            env=toolchain.command_env() if env is None else env,
            timeout=PLAYWRIGHT_PROBE_TIMEOUT_SECONDS,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return (
            "browser_playwright_probe_timeout: exceeded "
            f"{PLAYWRIGHT_PROBE_TIMEOUT_SECONDS} seconds"
        )
    except FileNotFoundError as exc:
        return f"browser_playwright_probe_unavailable: {exc}"
    except OSError as exc:
        return f"browser_playwright_probe_failed: {exc}"
    if _probe_passed(result):
        return None
    return (
        f"Playwright module load probe exited {result.returncode}\n"
        + _command_output_tail(result)
    )


def _probe_chromium_file(browser, toolchain, env):
    return _run_setup_command(
        [str(toolchain.node), "-e", browser_runtime_home.CHROMIUM_PRESENT_PROBE_JS],
        timeout=CHROMIUM_PROBE_TIMEOUT_SECONDS,
        reason="browser_chromium_probe_timeout",
        cwd=str(browser),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _ensure_cache_writable(cache: Path) -> None:
    try:
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=cache) as probe:
            probe.write(b"yoke-browser-cache-write-check")
            probe.flush()
    except OSError as exc:
        raise RuntimeError(
            f"browser_cache_not_writable: {cache}: {exc}; "
            "make this directory and its parents writable by the current user, "
            "then retry yoke qa browser setup"
        ) from exc


def ensure_browser_runtime(browser: Path | None = None, toolchain=None, *, emit=print):
    try:
        ensure_owner_only_directory(machine_config.yoke_home())
        return _ensure_browser_runtime(browser, toolchain, emit=emit)
    except OSError as exc:
        raise RuntimeError(
            f"browser_runtime_command_failed: {exc}. "
            "Check runtime files and executable permissions, then retry yoke qa browser setup."
        ) from exc


def chromium_status(browser: Path, toolchain) -> tuple[str, str | None]:
    """Check the machine's selection without installing or changing config."""
    env = toolchain.command_env()
    env["PLAYWRIGHT_BROWSERS_PATH"] = (
        resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None) or ""
    )
    saved = browser_executable.configured()
    browser_executable.project_environment(env, saved)
    try:
        if not saved:
            result = _probe_chromium_file(browser, toolchain, env)
            if not _probe_passed(result):
                return "missing", _command_output_tail(result)
        # Bundled-browser status checks the dependency without provisioning
        # AppArmor. Setup separately proves the sandbox mode it will use.
        result = browser_system_browser.probe_launch(
            browser, toolchain, env, saved, sandbox=bool(saved)
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return "missing", f"browser_chromium_probe_failed: {exc}"
    if _probe_passed(result):
        return "ready", None
    return "missing", _command_output_tail(result)


def _ensure_browser_runtime(browser: Path | None = None, toolchain=None, *, emit=print):
    browser = (
        browser if browser is not None else browser_runtime_home.ensure_materialized()
    )
    toolchain = toolchain or browser_node_toolchain.ensure_node_toolchain(emit=emit)
    _log = emit
    env = toolchain.command_env()
    cache = resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None)
    assert cache is not None
    _ensure_cache_writable(Path(cache))
    env["PLAYWRIGHT_BROWSERS_PATH"] = cache
    saved = browser_executable.configured()
    browser_executable.project_environment(env, None)
    autoinstall = os.environ.get("YOKE_BROWSER_AUTOINSTALL", "1")
    load_error = playwright_load_error(browser, toolchain, env=env)
    if load_error:
        if autoinstall == "0":
            raise RuntimeError(
                compose_refusal(
                    "browser_playwright_unloadable: YOKE_BROWSER_AUTOINSTALL=0\n"
                    + load_error,
                    recovery="Repair the runtime npm dependencies or enable autoinstall, "
                    "then retry yoke qa browser setup",
                )
            )
        _log(
            "[browser-auto-bootstrap] Playwright could not load; repairing npm dependencies..."
        )
        result = _run_setup_command(
            toolchain.package_command("npm", "install"),
            timeout=NPM_INSTALL_TIMEOUT_SECONDS,
            reason="browser_npm_install_timeout",
            cwd=str(browser),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"browser_npm_install_failed: exit {result.returncode}\n"
                + _command_output_tail(result)
                + "\ncheck network and runtime permissions, then retry yoke qa browser setup"
            )
        load_error = playwright_load_error(browser, toolchain, env=env)
        if load_error:
            raise RuntimeError(
                compose_refusal(
                    "browser_playwright_unloadable_after_install: npm exited 0\n"
                    + load_error,
                    recovery="Check the runtime npm dependencies and permissions, "
                    "then retry yoke qa browser setup",
                )
            )
        _log("[browser-auto-bootstrap] Playwright npm dependencies verified")

    result = _probe_chromium_file(browser, toolchain, env)
    installed = not _probe_passed(result)
    if installed:
        if saved and browser_system_browser.use_installed(
            browser, toolchain, env, emit=_log, saved=saved
        ):
            env.pop(SANDBOX_ENV, None)
            return env
        if autoinstall == "0":
            if browser_system_browser.use_installed(browser, toolchain, env, emit=_log):
                env.pop(SANDBOX_ENV, None)
                return env
            raise RuntimeError(
                compose_refusal(
                    "browser_chromium_unavailable: YOKE_BROWSER_AUTOINSTALL=0\n"
                    + _command_output_tail(result),
                    recovery="Install a usable Chromium or enable autoinstall, "
                    "then retry yoke qa browser setup",
                )
            )
        _log("[browser-auto-bootstrap] Chromium binary not found; auto-installing...")
        result = _run_setup_command(
            toolchain.package_command("npx", "playwright", "install", "chromium"),
            timeout=CHROMIUM_INSTALL_TIMEOUT_SECONDS,
            reason="browser_chromium_install_timeout",
            cwd=str(browser),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if result.returncode != 0:
            if browser_system_browser.use_installed(browser, toolchain, env, emit=_log):
                env.pop(SANDBOX_ENV, None)
                return env
            raise browser_system_browser.download_failure(
                result, _command_output_tail(result)
            )
        result = _probe_chromium_file(browser, toolchain, env)
        if not _probe_passed(result):
            raise _chromium_launch_failure(_command_output_tail(result), installed=True)
    sandbox_enabled = ensure_system_dependencies(
        browser,
        toolchain,
        env=env,
        emit=_log,
        autoinstall=autoinstall != "0",
    )
    env.pop(SANDBOX_ENV, None)
    if sandbox_enabled is False:
        env[SANDBOX_ENV] = "0"
    try:
        result = browser_system_browser.probe_launch(
            browser, toolchain, env, sandbox=sandbox_enabled is not False
        )
    except subprocess.TimeoutExpired as exc:
        raise _chromium_launch_failure(
            f"launch probe exceeded {exc.timeout} seconds", installed=installed
        ) from exc
    if not _probe_passed(result):
        raise _chromium_launch_failure(
            _command_output_tail(result), installed=installed
        )
    if installed:
        _log("[browser-auto-bootstrap] Chromium installation verified with a test page")
    if saved:
        browser_executable.save(None)
    return env


def _chromium_launch_failure(detail: str, *, installed: bool) -> RuntimeError:
    reason = (
        "browser_chromium_unusable_after_install: Chromium installer exited 0"
        if installed
        else "browser_chromium_unusable: bundled Chromium failed its launch check"
    )
    return RuntimeError(
        compose_refusal(
            f"{reason}\n{detail}",
            recovery="Check Chromium's binaries and OS dependencies, "
            "then retry yoke qa browser setup",
        )
    )

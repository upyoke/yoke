"""One browser installation path for onboarding and daemon startup."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from yoke_cli import browser_node_toolchain
from yoke_cli.config import browser_executable
from yoke_cli.config import machine_config
from yoke_cli.config.machine_config_file import ensure_owner_only_directory
from yoke_contracts.playwright_cache import (
    YOKE_BROWSER_CACHE_PROJECT,
    resolve_playwright_cache,
)
from yoke_harness import browser_runtime_home
from yoke_harness import browser_system_browser
from yoke_harness.browser_system_dependencies import ensure_system_dependencies


def _command_output_tail(result: subprocess.CompletedProcess) -> str:
    return "\n".join(
        f"{label} (last 20 lines, at most 4000 characters):\n"
        + ("\n".join((output or "").splitlines()[-20:])[-4000:] or "<empty>")
        for label, output in (("stdout", result.stdout), ("stderr", result.stderr))
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


def chromium_status(browser: Path, toolchain) -> str:
    """Check the machine's selection without installing or changing config."""
    env = toolchain.command_env()
    env["PLAYWRIGHT_BROWSERS_PATH"] = (
        resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None) or ""
    )
    saved = browser_executable.configured()
    browser_executable.project_environment(env, saved)
    try:
        if saved:
            result = browser_system_browser.probe_installed(
                browser, toolchain, env, saved
            )
        else:
            result = subprocess.run(
                [
                    str(toolchain.node),
                    "-e",
                    browser_runtime_home.CHROMIUM_PRESENT_PROBE_JS,
                ],
                cwd=str(browser),
                capture_output=True,
                text=True,
                env=env,
                timeout=40,
            )
    except (OSError, subprocess.TimeoutExpired):
        return "missing"
    return (
        "ready"
        if result.returncode == 0 and result.stdout.strip() == "ok"
        else "missing"
    )


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
    node_modules = browser / "node_modules"
    pw_modules = node_modules / "playwright"
    autoinstall = os.environ.get("YOKE_BROWSER_AUTOINSTALL", "1")
    if not node_modules.is_dir() or not pw_modules.is_dir():
        if autoinstall == "0":
            raise RuntimeError(
                "[browser-auto-bootstrap] BLOCKED: node_modules or playwright "
                "missing and YOKE_BROWSER_AUTOINSTALL=0"
            )
        _log(
            "[browser-auto-bootstrap] node_modules or playwright missing; auto-installing..."
        )
        result = subprocess.run(
            [str(toolchain.npm), "install"],
            cwd=str(browser),
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"browser_npm_install_failed: exit {result.returncode}\n"
                + _command_output_tail(result)
                + "\ncheck network and runtime permissions, then retry yoke qa browser setup"
            )
        _log("[browser-auto-bootstrap] npm install completed successfully")

    result = subprocess.run(
        [str(toolchain.node), "-e", browser_runtime_home.CHROMIUM_PRESENT_PROBE_JS],
        cwd=str(browser),
        capture_output=True,
        text=True,
        env=env,
    )
    chromium_status = result.stdout.strip() if result.returncode == 0 else "error"
    if chromium_status != "ok":
        if saved and browser_system_browser.use_installed(
            browser, toolchain, env, emit=_log, saved=saved
        ):
            return env
        if autoinstall == "0":
            if browser_system_browser.use_installed(browser, toolchain, env, emit=_log):
                return env
            raise RuntimeError(
                "[browser-auto-bootstrap] BLOCKED: Chromium binary missing"
            )
        _log("[browser-auto-bootstrap] Chromium binary not found; auto-installing...")
        result = subprocess.run(
            [str(toolchain.npx), "playwright", "install", "chromium"],
            cwd=str(browser),
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            if browser_system_browser.use_installed(browser, toolchain, env, emit=_log):
                return env
            raise browser_system_browser.download_failure(
                result, _command_output_tail(result)
            )
        _log("[browser-auto-bootstrap] Chromium installed successfully")
    ensure_system_dependencies(
        browser,
        toolchain,
        env=env,
        emit=_log,
        autoinstall=autoinstall != "0",
    )
    if saved:
        browser_executable.save(None)
    return env

"""One browser installation path for onboarding and daemon startup."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from yoke_cli import browser_node_toolchain
from yoke_harness import browser_runtime_home
from yoke_harness.browser_system_dependencies import ensure_system_dependencies


def ensure_browser_runtime(browser: Path | None = None, toolchain=None, *, emit=print):
    try:
        return _ensure_browser_runtime(browser, toolchain, emit=emit)
    except OSError as exc:
        raise RuntimeError(
            f"browser_runtime_command_failed: {exc}. "
            "Check runtime files and executable permissions, then retry yoke qa browser setup."
        ) from exc


def _ensure_browser_runtime(browser: Path | None = None, toolchain=None, *, emit=print):
    browser = (
        browser if browser is not None else browser_runtime_home.ensure_materialized()
    )
    toolchain = toolchain or browser_node_toolchain.ensure_node_toolchain(emit=emit)
    _log = emit
    env = toolchain.command_env()
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
                f"[browser-auto-bootstrap] npm install failed: {result.stderr}"
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
        if autoinstall == "0":
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
            raise RuntimeError(
                "browser_install_failed: "
                + (result.stderr or result.stdout)
                + "; check network and runtime permissions, then retry yoke qa browser setup"
            )
        _log("[browser-auto-bootstrap] Chromium installed successfully")
    ensure_system_dependencies(
        browser,
        toolchain,
        env=env,
        emit=_log,
        autoinstall=autoinstall != "0",
    )
    return env

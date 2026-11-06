"""Runtime interface for browser setup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class BrowserSetup(Protocol):
    """Operations and values supplied by the executing adapter."""

    CHROMIUM_INSTALL_TIMEOUT_SECONDS: Any
    CHROMIUM_PROBE_TIMEOUT_SECONDS: Any
    NPM_INSTALL_TIMEOUT_SECONDS: Any
    Path: Any
    SANDBOX_ENV: Any
    YOKE_BROWSER_CACHE_PROJECT: Any
    browser_executable: Any
    browser_node_toolchain: Any
    browser_runtime_home: Any
    browser_system_browser: Any
    chromium_status: Callable[..., Any]
    ensure_browser_runtime: Callable[..., Any]
    ensure_owner_only_directory: Any
    ensure_system_dependencies: Any
    machine_config: Any
    os: Any
    resolve_playwright_cache: Any
    subprocess: Any
    tempfile: Any
    terminal_detached_process: Any


def get_browser_setup() -> BrowserSetup:
    return cast(BrowserSetup, load_port("browser_setup", BrowserSetup))

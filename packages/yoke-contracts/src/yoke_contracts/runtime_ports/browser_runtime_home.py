"""Runtime interface for browser runtime home."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class BrowserRuntimeHome(Protocol):
    """Operations and values supplied by the executing adapter."""

    HASH_MARKER_NAME: Any
    RUNTIME_DIR_NAME: Any
    ensure_materialized: Callable[..., Any]
    package_source_root: Callable[..., Any]
    runtime_dir: Callable[..., Any]
    source_hash: Callable[..., Any]


def get_browser_runtime_home() -> BrowserRuntimeHome:
    return cast(BrowserRuntimeHome, load_port("browser_runtime_home", BrowserRuntimeHome))

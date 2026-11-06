"""Runtime interface for browser node toolchain."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class BrowserNodeToolchain(Protocol):
    """Operations and values supplied by the executing adapter."""

    MANAGED_NODE_VERSION: Any
    MINIMUM_NODE_MAJOR: Any
    NODE_DIST_BASE_URL: Any
    NodeToolchain: type[Any]
    NodeToolchainError: type[Any]
    ensure_node_toolchain: Callable[..., Any]
    managed_version_dir: Callable[..., Any]
    platform_archive_slug: Callable[..., Any]
    provision_managed_toolchain: Callable[..., Any]
    resolve_node_toolchain: Callable[..., Any]
    toolchain_status: Callable[..., Any]


def get_browser_node_toolchain() -> BrowserNodeToolchain:
    return cast(BrowserNodeToolchain, load_port("browser_node_toolchain", BrowserNodeToolchain))

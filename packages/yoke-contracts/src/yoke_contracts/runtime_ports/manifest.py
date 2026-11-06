"""Runtime interface for manifest."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class Manifest(Protocol):
    """Operations and values supplied by the executing adapter."""

    build_manifest: Callable[..., Any]
    diagnose_env_manifest_fetch: Callable[..., Any]
    fetch_env_manifest: Callable[..., Any]


def get_manifest() -> Manifest:
    return cast(Manifest, load_port("manifest", Manifest))

# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

import shutil

import subprocess

import tempfile

from pathlib import Path

from typing import List, Optional, Tuple

import pytest

from yoke_core.domain import (
    migration_fleet_preflight_extensions as extensions,
    migration_fleet_preflight_transfer as transfer,
    postgres_cluster,
)

from yoke_core.domain.postgres_cluster import ClusterSpec

VERSIONED_BIN_GLOB = "/usr/lib/postgresql/*/bin"


def _server_bin_dir() -> Tuple[Optional[Path], List[str]]:
    """The directory holding ``initdb``, plus the places that were tried."""
    searched: List[str] = []

    on_path = shutil.which("initdb")
    if on_path:
        return Path(on_path).parent, searched
    searched.append("PATH")

    if shutil.which("pg_config"):
        probe = subprocess.run(
            ["pg_config", "--bindir"], capture_output=True, text=True, timeout=30
        )
        candidate = Path(probe.stdout.strip()) if probe.stdout.strip() else None
        if candidate is not None:
            searched.append(str(candidate))
            if (candidate / "initdb").exists():
                return candidate, searched
    else:
        searched.append("pg_config (absent)")

    versioned = sorted(Path("/").glob(VERSIONED_BIN_GLOB.lstrip("/")))
    searched.append(VERSIONED_BIN_GLOB)
    for candidate in reversed(versioned):
        if (candidate / "initdb").exists():
            return candidate, searched

    return None, searched

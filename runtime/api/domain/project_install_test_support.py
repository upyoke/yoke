# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from yoke_core.domain.project_install import ProjectInstallError, apply_bundle

from yoke_core.domain.project_install_test_helpers import (
    DEFAULT_FILES,
    make_bundle,
)

MANIFEST_REL = ".yoke/install-manifest.json"


def _tree_bytes(root: Path) -> dict[str, bytes | str]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        snapshot[rel] = (
            f"symlink:{path.readlink()}"
            if path.is_symlink()
            else path.read_bytes()
            if path.is_file()
            else "directory"
        )
    return snapshot

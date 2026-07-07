"""Source-tree import path helpers for subprocess tests."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAMES = (
    "yoke-core",
    "yoke-contracts",
    "yoke-cli",
    "yoke-harness",
)
PACKAGE_ROOT = REPO_ROOT / "packages"
SOURCE_PYTHONPATH = os.pathsep.join(
    str(path)
    for path in (
        REPO_ROOT,
        *(PACKAGE_ROOT / package_name / "src" for package_name in PACKAGE_NAMES),
    )
)


__all__ = ["REPO_ROOT", "SOURCE_PYTHONPATH"]

# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import ast

from pathlib import Path

from typing import Iterator, List, Set, Tuple

from yoke_contracts.session_identity import AMBIENT_ENV_VARS

REPO_ROOT = Path(__file__).resolve().parents[3]

SOURCE_ROOTS = (
    *sorted(REPO_ROOT.glob("packages/*/src")),
    REPO_ROOT / ".yoke" / "doctor",
)


def source_files() -> Iterator[Path]:
    for root in SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            parts = path.parts
            if "__pycache__" in parts:
                continue
            yield path

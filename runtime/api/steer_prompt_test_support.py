# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_STEER_DIR = _REPO_ROOT / ".agents" / "skills" / "yoke" / "steer"


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name == "loop.md":
        text += _read(_STEER_DIR / "watching.md") + _read(
            _STEER_DIR / "fleet-findings.md"
        )
    return text

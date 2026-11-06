"""Shared default bundle dir authority."""

from __future__ import annotations

from pathlib import Path
from yoke_contracts.machine_config.paths import yoke_home


def default_bundle_dir() -> Path:
    """Keep server infrastructure in the selected machine home."""
    return yoke_home() / "yoke-server"

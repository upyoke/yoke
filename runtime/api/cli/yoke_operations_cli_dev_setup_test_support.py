# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli

from yoke_cli.config import source_checkout_activation


def _source_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "yoke-source"
    (checkout / "runtime" / "harness").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n',
        encoding="utf-8",
    )
    return checkout

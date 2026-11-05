# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from runtime.api.cli.product_boundary_test_support import (
    command_inventory,
)

from yoke_cli import product_boundary_inventory as inventory

from yoke_cli import product_boundary_teaching as teaching


def _rows() -> dict[str, inventory.InventoryRow]:
    return {row.command_helper: row for row in command_inventory()}

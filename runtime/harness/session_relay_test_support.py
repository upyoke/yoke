# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_cli.config.machine_config import ConfiguredProject

from yoke_harness import session_relay

from yoke_harness import session_relay_inventory as inventory_module

from yoke_harness import session_relay_runtime as runtime

from yoke_harness import session_relay_working_directory as directories

from yoke_harness.session_relay_inventory import RelayInventory

from yoke_harness.session_relay_runtime import RelayAdapterResult

from yoke_harness.session_relay_schedule import (
    poll_is_due,
    record_next_poll,
    relay_run_lock,
)

MACHINE_ID = "11111111-1111-4111-8111-111111111111"


def _inventory() -> RelayInventory:
    return RelayInventory(
        relay_id=f"machine:{MACHINE_ID}",
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        project_ids=(10,),
        surface_versions={"codex-cli": "0.148.0a15"},
    )

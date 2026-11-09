# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from dataclasses import replace

import json

import pytest

from yoke_contracts.timestamps import parse_instant

from yoke_contracts.session_control.native_models import models_reading, native_model

from yoke_contracts.level_defaults import DEFAULT_LEVELS

from yoke_core.domain.session_launch_requests import create_launch

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility

from yoke_core.domain.session_launch_level_selection import preview_level_launch

from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError

from yoke_core.domain.universe_levels import write_universe_levels

from yoke_core.domain.workflow_stage_levels import default_launch_level

from runtime.api.domain.session_launch_level_test_support import (
    CODEX_SOL,
    EXTRA_OFF,
    add_surface as _add_surface,
    level_connection,
    pin_live_workers,
    weekly,
)

from runtime.api.domain.session_launch_test_support import NOW, authorization

from runtime.api.domain.session_launch_terminal_admission_test_support import (
    _pin_definition,
    _seed_pinned_item,
)


def add_surface(conn, machine_id, surface, windows=None):
    """These accounts bill no paid extra usage, so an empty pool blocks."""
    _add_surface(conn, machine_id, surface, windows, EXTRA_OFF)


def staged_launch(monkeypatch, *, capacity=50):
    pin_live_workers(monkeypatch, {})
    conn = level_connection(CODEX_SOL)
    write_universe_levels(conn, list(DEFAULT_LEVELS), actor_id=1)
    add_surface(conn, "worker-machine", "codex-cli", [weekly(capacity)])
    reading = models_reading(
        "codex-cli",
        [
            native_model("gpt-6.1-sol", reasoning_efforts=["low", "medium"]),
            native_model("gpt-6.1-terra", reasoning_efforts=["low", "high"]),
            native_model("gpt-6-astra", reasoning_efforts=["low", "medium", "xhigh"]),
        ],
        source="native fixture",
        observed_at=NOW,
    )
    conn.execute(
        "UPDATE session_relays SET surface_native_models=?",
        (json.dumps({"codex-cli": reading}),),
    )
    definition = _pin_definition()
    for stage in definition["stages"]:
        if stage["id"] == "implementing":
            stage["level"] = "INTERN"
    ref = _seed_pinned_item(conn, status="implementing", definition=definition)
    conn.execute("ALTER TABLE items ADD COLUMN workflow_posture TEXT DEFAULT '{}'")
    conn.execute(
        "UPDATE items SET workflow_posture=?",
        (
            json.dumps(
                {"level": {"shift": 1, "max": "SENIOR", "reason": "One step up"}}
            ),
        ),
    )
    conn.commit()
    return conn, LaunchRequest(
        project_id=10,
        executor_surface="",
        item=ref,
        instructions="Resume the same item",
        idempotency_key="effective-stage",
    )

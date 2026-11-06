# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.independent_member_delivery_close_out_test_support import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver

from yoke_core.domain.deployment_run_auto_completion import finish_ready_run


def _run_status(conn: Any, run_id: str) -> str:
    return str(
        conn.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
    )

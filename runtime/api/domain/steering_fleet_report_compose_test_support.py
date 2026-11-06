# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    acquire_steering,
    seed_standard_steering_world,
    seed_strategy_doc,
)

from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport

from yoke_core.domain.steering_fleet_report_capacity import (
    SessionCount,
    SurfaceReadiness,
)

from yoke_core.domain.steering_fleet_report_compose import (
    combined_body,
    compose_held_reports,
    steering_scope_descriptor,
)

from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit

NOW = "2026-08-29T12:00:00.000000Z"


def _report(
    project_id: int,
    now: str,
    *,
    idle: tuple[ClaimHolder, ...] = (),
    launchable: tuple[SurfaceReadiness, ...] = (),
    session_counts: tuple[SessionCount, ...] = (),
    origin_counts: tuple[tuple[str, int], ...] = (),
    plan_limits: tuple[MachinePlanLimit, ...] = (),
) -> FleetReport:
    return FleetReport(
        project_id=project_id,
        composed_at=now,
        staffing_after_seconds=60,
        idle_after_seconds=60,
        available=(),
        holders=(),
        idle=idle,
        undelivered=(),
        unregistered_launches=(),
        landed_open=(),
        dead_waits=(),
        launchable=launchable,
        session_counts=session_counts,
        origin_counts=origin_counts,
        plan_limits=plan_limits,
    )


def _idle(project_id: int) -> ClaimHolder:
    return ClaimHolder(
        session_id=f"idle-{project_id}",
        item_id=project_id,
        public_ref=f"X-{project_id}",
        mode="wait",
        parked=False,
        last_activity_at="2026-08-29T11:00:00.000000Z",
        idle_seconds=3600,
    )

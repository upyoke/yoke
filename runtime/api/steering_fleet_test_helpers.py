"""Shared scope seeding for the steering fleet report's tests.

Composition, rendering, and the detectors are three test modules reading
one fleet, so the sessions, relay, and steering claim that make up that
fleet are seeded here once rather than copied into each of them.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant
from runtime.api.steering_fleet_seed_rows import (
    NOW as NOW,
    LONG_AGO as LONG_AGO,
    BEFORE_THAT as BEFORE_THAT,
    JUST_NOW as JUST_NOW,
    NOT_YET_EXPIRED as NOT_YET_EXPIRED,
    STAFFING_SECONDS as STAFFING_SECONDS,
    IDLE_SECONDS as IDLE_SECONDS,
    SURFACE as SURFACE,
    STEERING_SESSION as STEERING_SESSION,
    WORKER_SESSION as WORKER_SESSION,
    ASKER as ASKER,
    ANSWERER as ANSWERER,
    PROJECT_ID as PROJECT_ID,
    PLAN_LIMIT_HOST as PLAN_LIMIT_HOST,
    RELAY_HOSTNAME as RELAY_HOSTNAME,
    ACTOR_ID as ACTOR_ID,
    seed_session as seed_session,
    seed_tool_call as seed_tool_call,
    seed_denial as seed_denial,
    seed_message as seed_message,
    seed_delivery_attempt as seed_delivery_attempt,
    seed_relay as seed_relay,
)

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.session_control.plan_limits import ALL_MODELS_SCOPE
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.steering_fleet_report import ClaimHolder, compose_report
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.strategy_docs_defaults import seed_default_docs


def compose(
    conn,
    session_id: str = STEERING_SESSION,
    now: str = NOW,
    scope: dict | None = None,
):
    """One report at the project's default thresholds, for one seat's scope."""
    return compose_report(
        conn,
        project_id=PROJECT_ID,
        session_id=session_id,
        staffing_after_seconds=STAFFING_SECONDS,
        idle_after_seconds=IDLE_SECONDS,
        now=now,
        scope=scope,
    )


def quiet_holder(session_id: str, item_id: int = 1) -> ClaimHolder:
    """A holder that has said nothing for three hours."""
    return ClaimHolder(
        session_id=session_id,
        item_id=item_id,
        public_ref=f"YOK-{item_id}",
        mode="wait",
        parked=False,
        last_activity_at=parse_instant(LONG_AGO),
        idle_seconds=3 * 3600,
    )


def seed_steering_scope(conn):
    """A steering holder, a connected relay, and three long-unpicked items.

    A plain function rather than a fixture: a fixture imported by name
    reads as a redefinition at every test that takes it, so each module
    wraps this in its own three-line fixture instead.
    """
    seed_session(conn, STEERING_SESSION)
    seed_session(conn, WORKER_SESSION, last_tool_call_at=LONG_AGO)
    seed_relay(conn)
    for item_id in (1, 2, 3):
        insert_item(
            conn,
            id=item_id,
            title=f"Unpicked work {item_id}",
            status="idea",
            created_at=LONG_AGO,
            updated_at=LONG_AGO,
            spec=f"# Unpicked work {item_id}\n\nA real spec body.",
        )
    conn.commit()
    seed_default_docs(conn, PROJECT_ID, "Yoke")
    acquire_steering(
        conn,
        session_id=STEERING_SESSION,
        project_id=PROJECT_ID,
        reason="steering",
    )
    return conn


def plan_limit_row(
    *,
    machine_id: str = "machine-1",
    machine_name: str = PLAN_LIMIT_HOST,
    surface: str = "cursor-cli",
    plan_tier: str | None = "Ultra",
    window_kind: str = "monthly",
    scope: str = ALL_MODELS_SCOPE,
    meter: str = "planUsage.totalPercentUsed",
    remaining_percent: float | None = 22.0,
    resets_at: str | None = "2026-09-07T01:00:00.000000Z",
    status: str = "ok",
    reason: str | None = None,
) -> MachinePlanLimit:
    """One (machine, surface, window) meter for the report renderers."""
    return MachinePlanLimit(
        machine_id=machine_id,
        machine_name=machine_name,
        surface=surface,
        plan_tier=plan_tier,
        window_kind=window_kind,
        scope=scope,
        meter=meter,
        remaining_percent=remaining_percent,
        resets_at=resets_at,
        status=status,
        reason=reason,
    )


__all__ = [
    "ACTOR_ID",
    "ANSWERER",
    "ASKER",
    "BEFORE_THAT",
    "IDLE_SECONDS",
    "JUST_NOW",
    "LONG_AGO",
    "NOT_YET_EXPIRED",
    "NOW",
    "PLAN_LIMIT_HOST",
    "PROJECT_ID",
    "STAFFING_SECONDS",
    "STEERING_SESSION",
    "SURFACE",
    "WORKER_SESSION",
    "compose",
    "plan_limit_row",
    "quiet_holder",
    "seed_delivery_attempt",
    "seed_denial",
    "seed_message",
    "seed_relay",
    "seed_session",
    "seed_steering_scope",
    "seed_tool_call",
]

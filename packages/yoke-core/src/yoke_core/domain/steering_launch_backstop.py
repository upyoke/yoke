"""Keep a steering scope staffed without displacing human-opened sessions.

Both lanes coexist. People keep opening their own sessions and pulling work
the ordinary way; this operation only notices work the scheduler already
calls runnable that nobody claimed, and that has now waited longer than the
project's grace period. For that work it files ordinary launches through the
existing launch plane — no new spawn mechanics — capped by the scope's
concurrent-worker budget and stamped with the origin that tells a staffed
worker apart from one an operator asked for.

Re-running is safe by construction: each gap carries one deterministic
idempotency key, so a second evaluation over the same unstaffed work
deduplicates onto the launch the first one filed.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_STEERING_BACKSTOP,
)
from yoke_core.domain import db_backend
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.scheduler import compute_schedule
from yoke_core.domain.scheduler_types import ClaimState, NextStep
from yoke_core.domain.session_launch_projection import public_launch_record
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_store import utc_now
from yoke_core.domain.session_launch_types import (
    DEFAULT_LAUNCH_DEADLINE_SECONDS,
    DEFAULT_MAX_BODY_BYTES,
    LaunchAuthorization,
    LaunchRequest,
    SessionLaunchError,
)
from yoke_core.domain.steering_backstop_selection import (
    BackstopCandidate,
    backstop_gap_item_id,
    backstop_idempotency_key,
    backstop_instruction,
    select_backstop_work,
)


EVENT_STEERING_BACKSTOP_EVALUATED = "SteeringBackstopEvaluated"

#: Launch states that still occupy a worker slot: the launch is on its way,
#: or it succeeded and the session it produced has not ended.
_PENDING_LAUNCH_STATES = ("queued", "assigned", "launching", "awaiting_registration")

CandidatePort = Callable[..., Sequence[BackstopCandidate]]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def require_steering_holder(conn: Any, *, session_id: str, project_id: int) -> int:
    """Return the caller's live steering claim id, or refuse."""
    from yoke_core.domain.steering_claims import list_claims

    for claim in list_claims(
        conn,
        project_id=int(project_id),
        session_id=session_id,
        active_only=True,
    ):
        return int(claim["id"])
    raise SessionLaunchError(
        "steering_claim_required",
        "the steering backstop runs from the live steering claim holder; "
        f"acquire it with `yoke claims steering acquire --project {project_id}`",
    )


def _unpicked_since(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    """When each item last became pickable.

    The later of its own last change and the last release of a claim on it —
    a released claim means the work went back on the board at that moment,
    however old the item itself is.
    """
    if not item_ids:
        return {}
    marker = _p(conn)
    holes = ", ".join(marker for _ in item_ids)
    rows = conn.execute(
        f"""SELECT i.id AS id,
                   i.updated_at AS updated_at,
                   i.created_at AS created_at,
                   MAX(c.released_at) AS released_at
              FROM items i
              LEFT JOIN work_claims c
                ON c.target_kind = 'item'
               AND c.released_at IS NOT NULL
               AND {_scope_item_id(conn)} = i.id
             WHERE i.id IN ({holes})
             GROUP BY i.id, i.updated_at, i.created_at""",
        tuple(int(item_id) for item_id in item_ids),
    ).fetchall()
    resolved: dict[int, str] = {}
    for row in rows:
        record = dict(row)
        stamps = [
            str(record.get(name) or "")
            for name in ("updated_at", "created_at", "released_at")
        ]
        resolved[int(record["id"])] = max(stamp for stamp in stamps if stamp)
    return resolved


def _scope_item_id(conn: Any) -> str:
    from yoke_core.domain.work_claim_targets import scope_int_sql

    return scope_int_sql(conn, "c.scope", "item_id")


def scope_candidates(
    conn: Any,
    *,
    project_id: int,
    session_id: str,
) -> tuple[BackstopCandidate, ...]:
    """Runnable, unclaimed, dispatchable steps in one steering scope.

    A stale claim is deliberately not a candidate: the work still has a
    holder until the stale-session sweep releases it, and staffing over one
    would hand a worker an item it cannot claim.
    """
    schedule = compute_schedule(
        conn,
        [int(project_id)],
        session_id=session_id,
        emit_events=False,
    )
    steps = [
        step
        for step in schedule.ranked_steps
        if step.claim_state is ClaimState.UNCLAIMED
        and step.next_step is not NextStep.WAIT
    ]
    refs = render_item_refs(conn, [step.item_id for step in steps])
    pickable = _unpicked_since(conn, [step.item_id for step in steps])
    return tuple(
        BackstopCandidate(
            item_id=step.item_id,
            item_ref=refs.get(step.item_id, str(step.item_id)),
            title=step.title,
            next_step=step.next_step.value,
            rank=step.rank,
            unpicked_since=pickable.get(step.item_id) or step.created_at,
        )
        for step in steps
    )


def staffed_item_ids(conn: Any, *, project_id: int) -> frozenset[int]:
    """Items this scope already has a backstop-staffed worker coming for."""
    marker = _p(conn)
    states = ", ".join(marker for _ in _PENDING_LAUNCH_STATES)
    rows = conn.execute(
        f"""SELECT launch.idempotency_key AS gap_key
              FROM session_launches launch
              LEFT JOIN harness_sessions worker
                ON worker.session_id = launch.registered_session_id
             WHERE launch.project_id = {marker}
               AND launch.origin = {marker}
               AND (launch.state IN ({states})
                    OR (launch.state = 'succeeded'
                        AND worker.session_id IS NOT NULL
                        AND worker.ended_at IS NULL))""",
        (int(project_id), LAUNCH_ORIGIN_STEERING_BACKSTOP, *_PENDING_LAUNCH_STATES),
    ).fetchall()
    gaps = (backstop_gap_item_id(dict(row)["gap_key"]) for row in rows)
    return frozenset(item_id for item_id in gaps if item_id is not None)


def run_backstop(
    conn: Any,
    *,
    session_id: str,
    project_id: int,
    auth: LaunchAuthorization,
    executor_surface: str,
    unpicked_after_seconds: int,
    worker_budget: int,
    model: str | None = None,
    deadline_seconds: int = DEFAULT_LAUNCH_DEADLINE_SECONDS,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    surface_fallback_enabled: bool = False,
    auto_select_machine: bool = False,
    dry_run: bool = False,
    now: str | None = None,
    candidates: CandidatePort = scope_candidates,
) -> dict[str, Any]:
    """Evaluate one steering scope and staff the work nobody picked up."""
    claim_id = require_steering_holder(
        conn, session_id=session_id, project_id=int(project_id)
    )
    current = now or utc_now()
    selection = select_backstop_work(
        candidates(conn, project_id=int(project_id), session_id=session_id),
        now=current,
        unpicked_after_seconds=int(unpicked_after_seconds),
        worker_budget=int(worker_budget),
        staffed_item_ids=staffed_item_ids(conn, project_id=int(project_id)),
    )

    launched: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    if not dry_run:
        for candidate in selection.staff:
            outcome = _launch_one(
                conn,
                candidate=candidate,
                auth=auth,
                session_id=session_id,
                project_id=int(project_id),
                executor_surface=executor_surface,
                model=model,
                deadline_seconds=deadline_seconds,
                max_body_bytes=max_body_bytes,
                surface_fallback_enabled=surface_fallback_enabled,
                auto_select_machine=auto_select_machine,
                now=current,
            )
            (refused if "error" in outcome else launched).append(outcome)

    result = {
        "project_id": int(project_id),
        "steering_claim_id": claim_id,
        "evaluated_at": current,
        "dry_run": bool(dry_run),
        "unpicked_after_seconds": int(unpicked_after_seconds),
        "launched": launched,
        "refused": refused,
        **selection.to_dict(),
    }
    _emit_evaluated(session_id, result)
    return result


def _launch_one(
    conn: Any,
    *,
    candidate: BackstopCandidate,
    auth: LaunchAuthorization,
    session_id: str,
    project_id: int,
    executor_surface: str,
    model: str | None,
    deadline_seconds: int,
    max_body_bytes: int,
    surface_fallback_enabled: bool,
    auto_select_machine: bool,
    now: str,
) -> dict[str, Any]:
    request = LaunchRequest(
        project_id=project_id,
        executor_surface=executor_surface,
        instructions=backstop_instruction(candidate, report_to_session_id=session_id),
        idempotency_key=backstop_idempotency_key(project_id, candidate.item_id),
        model=model,
        allow_surface_fallback=surface_fallback_enabled,
        deadline_seconds=deadline_seconds,
        origin=LAUNCH_ORIGIN_STEERING_BACKSTOP,
    )
    try:
        outcome = create_launch(
            conn,
            auth=auth,
            request=request,
            max_body_bytes=max_body_bytes,
            surface_fallback_enabled=surface_fallback_enabled,
            auto_select_machine=auto_select_machine,
            now=now,
        )
    except SessionLaunchError as exc:
        return {
            "item_id": candidate.item_id,
            "item_ref": candidate.item_ref,
            "error": exc.code,
            "message": str(exc),
        }
    return {
        "item_id": candidate.item_id,
        "item_ref": candidate.item_ref,
        "deduplicated": outcome.deduplicated,
        "launch": public_launch_record(outcome.launch),
    }


def _emit_evaluated(session_id: str, result: dict[str, Any]) -> None:
    from yoke_core.domain import sessions_analytics as analytics

    analytics._emit_session_event(
        EVENT_STEERING_BACKSTOP_EVALUATED,
        session_id=session_id,
        context={
            "project_id": result["project_id"],
            "steering_claim_id": result["steering_claim_id"],
            "dry_run": result["dry_run"],
            "worker_budget": result["worker_budget"],
            "workers_in_flight": result["workers_in_flight"],
            "newly_staffed_item_ids": [entry["item_id"] for entry in result["staff"]],
            "launched_count": len(result["launched"]),
            "refused_count": len(result["refused"]),
            "withheld_count": len(result["withheld"]),
        },
    )


__all__ = [
    "EVENT_STEERING_BACKSTOP_EVALUATED",
    "require_steering_holder",
    "run_backstop",
    "scope_candidates",
    "staffed_item_ids",
]

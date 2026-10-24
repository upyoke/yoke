"""Admit capacity successors and transfer their predecessor's exact claim."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.timestamps import parse_instant

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.session_capacity_recovery import (
    capacity_catalog,
    capacity_model_key,
)
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.session_vendor_error_states import vendor_error_states
from yoke_core.domain.work_claim_holder import holder_session_for_item


def _refuse(detail: str) -> None:
    raise SessionLaunchError(
        "capacity_recovery_custody_changed",
        (
            compose_refusal(
                f"Capacity successor custody changed: {detail}.",
                recovery="steering must inspect the current holder and launch before restaffing; preserve its lane.",
            )
        ),
    )


def _stopped_state(conn: Any, *, predecessor: str, project_id: int, now: Any) -> dict:
    p = placeholder(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    conn.execute(
        f"SELECT session_id FROM harness_sessions WHERE session_id={p}{lock}",
        (predecessor,),
    ).fetchone()
    from yoke_core.domain.session_resume_in_flight import resume_in_flight

    if resume_in_flight(conn, predecessor, now=parse_instant(now)) is not None:
        _refuse("predecessor has an accepted resume in flight")
    states = vendor_error_states(
        conn, authorized_projects=(project_id,), now=parse_instant(now)
    )
    state = next((s for s in states if s["session_id"] == predecessor), None)
    if state is None or state["status"] not in {
        "relaunch_due",
        "capacity_recovery_pending",
        "capacity_recovery_refused",
    }:
        _refuse("predecessor is no longer stopped on model capacity")
    return state


def admit_capacity_predecessor(
    conn: Any, *, request: Any, auth: Any, now: Any
) -> dict | None:
    predecessor = request.capacity_predecessor_session_id
    if not predecessor:
        return None
    state = _stopped_state(
        conn, predecessor=predecessor, project_id=request.project_id, now=now
    )
    item_id = resolve_item_ref_or_none(conn, request.item, project=request.project_id)
    holder = holder_session_for_item(conn, item_id)
    if holder.get("holder_session_id") != predecessor:
        _refuse("predecessor no longer holds the assigned item")
    p = placeholder(conn)
    claims = conn.execute(
        f"SELECT id FROM work_claims WHERE session_id={p} AND released_at IS NULL",
        (predecessor,),
    ).fetchall()
    if len(claims) != 1 or int(claims[0][0]) != holder["claim_id"]:
        _refuse("predecessor holdings are not one exclusive item claim")
    excluded = capacity_model_key(
        state["executor_surface"],
        state["model"],
        records=capacity_catalog(conn, now=now),
    )
    if (
        request.level != state["execution_level"]
        or request.machine_id != state["machine_id"]
        or auth.actor_id != state["actor_id"]
        or excluded not in request.excluded_models
    ):
        _refuse(
            "successor must preserve actor, level and lane machine and exclude the refused model"
        )
    return {
        "predecessor_session_id": predecessor,
        "claim_id": holder["claim_id"],
        "item_id": item_id,
        "episode_key": state["episode_key"],
        "excluded_models": list(request.excluded_models),
        "reason": state["error_message"],
    }


def transfer_capacity_claim(
    conn: Any, *, launch: Any, session_id: str, now: Any
) -> None:
    """Inside exact registration, retain claim identity and retire the old native."""
    placement = json_helper.loads_text(launch.level_placement or "{}")
    recovery = placement.get("capacity_recovery")
    if not recovery:
        return
    predecessor = recovery["predecessor_session_id"]
    p = placeholder(conn)
    # Lock in the same item/session order as launch create before transferring.
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    conn.execute(
        f"SELECT id FROM items WHERE id={p}{lock}", (recovery["item_id"],)
    ).fetchone()
    conn.execute(
        f"SELECT session_id FROM harness_sessions WHERE session_id={p}{lock}",
        (predecessor,),
    ).fetchone()
    claim = conn.execute(
        f"SELECT session_id,released_at FROM work_claims WHERE id={p}{lock}",
        (recovery["claim_id"],),
    ).fetchone()
    if claim and claim[0] == session_id and claim[1] is None:
        return
    if claim is None or claim[0] != predecessor or claim[1] is not None:
        _refuse("recorded claim was released or reassigned")
    state = _stopped_state(
        conn, predecessor=predecessor, project_id=launch.project_id, now=now
    )
    if state["episode_key"] != recovery["episode_key"]:
        _refuse("predecessor performed new work after the capacity observation")
    if state["actor_id"] != launch.requester_actor_id:
        _refuse("predecessor actor changed")
    if state["machine_id"] != launch.assigned_machine_id:
        _refuse("predecessor lane machine changed")
    target_actor = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={p}", (session_id,)
    ).fetchone()
    if not target_actor or target_actor[0] != state["actor_id"]:
        _refuse("registered successor actor differs")
    if (
        capacity_model_key(
            launch.selected_surface,
            launch.resolved_model,
            records=capacity_catalog(conn, now=now),
        )
        in recovery["excluded_models"]
    ):
        _refuse("successor selected the overloaded model")
    from yoke_core.domain.session_message_store import cancel_open_recipients
    from yoke_core.domain.session_steering_authority import session_control_target
    from yoke_core.domain.session_termination import _queue_reap
    from yoke_core.domain.sessions_render_attribution import (
        clear_current_item,
        set_current_item,
    )

    target = session_control_target(conn, predecessor)
    stamp = instant_parameter(conn, parse_instant(now))
    conn.execute(
        f"UPDATE work_claims SET session_id={p},last_heartbeat={p} WHERE id={p}",
        (session_id, stamp, recovery["claim_id"]),
    )
    clear_current_item(conn, predecessor, commit=False)
    set_current_item(conn, session_id, str(recovery["item_id"]), commit=False)
    cancel_open_recipients(
        conn,
        session_id=predecessor,
        cancelled_at=parse_instant(now),
        result_code="capacity_successor_registered",
    )
    _queue_reap(conn, target=target, requested_at=parse_instant(now))
    conn.execute(
        f"UPDATE harness_sessions SET terminated_at={p},ended_at={p},termination_reason={p},"
        f"terminated_by_actor_id={p},terminated_by_session_id={p} WHERE session_id={p}",
        (
            stamp,
            stamp,
            f"capacity successor {launch.launch_id} registered as {session_id}",
            launch.requester_actor_id,
            session_id,
            predecessor,
        ),
    )


def admit_assigned_launch(
    conn: Any, *, request: Any, auth: Any, preview: Any, now: Any
) -> Any:
    """Keep worker admission and capacity evidence in one transaction seam."""
    from yoke_core.domain.session_launch_assignment import refuse_held_assigned_item

    recovery = admit_capacity_predecessor(conn, request=request, auth=auth, now=now)
    if request.item:
        refuse_held_assigned_item(
            conn,
            public_ref=request.item,
            project_id=request.project_id,
            predecessor_session_id=auth.session_id,
            successor_level=request.level,
            capacity_predecessor_session_id=request.capacity_predecessor_session_id,
        )
    return (
        replace(
            preview,
            level_placement={
                **(preview.level_placement or {}),
                "capacity_recovery": recovery,
            },
        )
        if recovery
        else preview
    )

"""Server-owned single-item worker mandate composed at launch create."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.launch_origin import LAUNCH_ORIGIN_STEERING
from yoke_contracts.session_control.models import LaunchCreateRequest
from yoke_core.domain.project_identity import resolve_item_id
from yoke_core.domain.session_launch_origin import derived_launch_origin
from yoke_core.domain.session_launch_store import marker, value
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.session_workflow_routing import live_next_step
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


_ENTRYPOINTS = {
    "dash": "/yoke dash {ref}",
    "refine": "/yoke refine {ref}",
    "advance": "/yoke advance {ref} implementation",
    "polish": "/yoke polish {ref}",
    "blitz": "/yoke blitz {ref}",
    "shepherd": "/yoke shepherd {ref}",
    "conduct": "/yoke conduct {ref}",
    "usher": "/yoke usher {ref}",
}
_REMAINING_LEGS = {
    "dash": "the Dash leg to its merge/evidence close",
    "refine": (
        "refine to refined-idea, then implementation, polish, and that "
        "binding's merge boundary"
    ),
    "advance": (
        "implementation and polish per the live bindings, then that "
        "binding's merge boundary"
    ),
    "polish": "polish per the live bindings, then that binding's merge boundary",
    "blitz": (
        "the Blitz leg after the strategy-document handoff, through its "
        "merge/evidence close"
    ),
    "shepherd": (
        "the shepherd, conduct, and usher chain named by the live bindings, "
        "stopping before any deployment run"
    ),
    "conduct": (
        "the conduct and usher chain named by the live bindings, stopping "
        "before any deployment run"
    ),
    "usher": "usher through merge; do not create a deployment run",
}


HEADLESS_LANDING_WAIT_TEACHING = (
    "You are a headless command that cannot be prompted again, so a "
    "merge-queue landing is not a place to stop. When your merge returns "
    "landing_pending=true, do not end the pass on it: pass --wait and hold "
    "the turn on the merge watcher wrapper the way your skill's merge step "
    "spells out. Merged closes the item out in that same turn; a stopped "
    "landing rebases, re-runs the verification gate, and re-runs the same "
    "command; only the poll budget running out ends the turn, and then you "
    'stamp `yoke sessions touch --mode parked --reason "<observed landing '
    'state>"` and report a HUMAN_GATE naming the pull request, that reading, '
    "and the resume command. Never end a turn on a landing you did not read."
)


TURN_END_RELAY_TEACHING = (
    "Your DONE report IS the last assistant text of the turn you stop on: "
    "the Stop hook delivers that text to the steering seat automatically, "
    "once, and it still reaches the seat after close-out released your item "
    "claim. Write that text as the report — lead with `DONE <item> "
    "<one-line summary>`, then what landed, what is blocked, what you need — "
    "and never re-send it with `yoke say`. Keep `yoke say` for what cannot "
    "wait for a turn end. Only a turn that names something to act on — a "
    "failure, a blocker, a conflict, a decision, a question, or a terminal "
    "outcome — is delivered; a turn ending in a wait, a status verb, or a "
    "progress note is recorded on the ledger as SteeringReportSkipped "
    "instead, so stopping on one costs the seat nothing and tells it "
    "nothing either."
)

_RELAYED_CLOSE = (
    "When those legs are complete, END your session — do not pick up further "
    "work, do not chain into other items."
)

_SELF_REPORTED_CLOSE = (
    "When those legs are complete, message the orchestrator "
    '(printf %s "DONE {ref} <one-line summary>" | yoke say --stdin '
    "--steering) and END your session — do not pick up further work, do not "
    "chain into other items. Send that report before releasing any claim you "
    "still hold; after a close-out that already released it, --steering "
    "resolves from the item you last held in this session, and a repeat of "
    "the same DONE is deduplicated rather than delivered twice."
)


def compose_single_item_mandate(
    *,
    public_ref: str,
    entrypoint: str,
    remaining_legs: str,
    steering_launched: bool,
    extras: str = "",
) -> str:
    """Return the canonical item-bound worker mandate, with optional extras.

    The report target is the steering ROLE, never the launching session.
    Baking a session id in made every mandate outlive its own address: when
    the operator stopped that seat, each later report drove a headless
    resume of a dead session that acknowledged and never answered, and the
    successor seat had to redirect every live worker by hand.

    Only a steering-launched worker is told about the turn-end relay,
    because only a steering-launched worker gets one: the Stop-hook route
    covers exactly the sessions a seat launched. Teaching it to an
    operator-launched worker would promise a delivery that never happens.

    The landing teaching, by contrast, is unconditional: every composed
    mandate belongs to a launched CLI session, and a launched session of
    any origin is a headless command that cannot be re-entered on the
    landing-complete message. A worker that stopped on that handoff left
    its branch landed and its item at reviewing-implementation with
    nobody to close it out, seven times in one night.

    That worker is also the only one given a manual DONE step. Handing a
    relayed worker both routes is what delivered the same report twice in
    one day: its turn-end text reached the seat, and so did the `yoke say`
    the mandate asked for. A relayed worker stops; an unrelayed one sends.
    """
    close = (
        _RELAYED_CLOSE
        if steering_launched
        else _SELF_REPORTED_CLOSE.format(ref=public_ref)
    )
    mandate = (
        f"{entrypoint}\n\n"
        f"Single-item mandate (steering): acquire the {public_ref} work claim "
        f"as your FIRST action, then execute only {public_ref} through "
        f"{remaining_legs}. Do NOT create or dispatch any deployment run — "
        "the orchestrator batches deploys. Message the orchestrator ONLY for "
        "substantive updates — a red gate and what failed, a blocker, a conflict "
        "with this instruction, a defect outside your scope, a decision you need. "
        "NEVER send progress: no percentages, elapsed-time polls, watcher "
        'heartbeats, or "still green" notes; relay those in your own output '
        f"instead. {close} If your claim is swept mid-work, reacquire and "
        "continue."
    )
    mandate = f"{mandate}\n\n{HEADLESS_LANDING_WAIT_TEACHING}"
    if steering_launched:
        mandate = f"{mandate}\n\n{TURN_END_RELAY_TEACHING}"
    extra = extras.strip()
    return f"{mandate}\n\n{extra}" if extra else mandate


def _route_for_item(conn: Any, public_ref: str, project_id: int) -> tuple[str, str]:
    item_id = resolve_item_id(conn, public_ref, project=project_id)
    if item_id is None:
        raise SessionLaunchError(
            "assignment_item_not_found",
            f"assignment item {public_ref!r} was not found; pass a current item ref",
        )
    query = marker(conn)
    row = conn.execute(
        f"SELECT status FROM items WHERE id={query}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise SessionLaunchError(
            "assignment_item_not_found",
            f"assignment item {public_ref!r} was not found; pass a current item ref",
        )
    try:
        workflow = load_item_workflow_runtime(conn, item_id)
    except WorkflowRegistryError as exc:
        raise SessionLaunchError("mandate_unroutable", str(exc)) from exc
    step = live_next_step(
        workflow,
        str(value(row, "status", 0) or ""),
        conn=conn,
        item_id=item_id,
    )
    entrypoint = _ENTRYPOINTS.get(str(step or ""))
    remaining = _REMAINING_LEGS.get(str(step or ""))
    if not entrypoint or not remaining:
        raise SessionLaunchError(
            "mandate_unroutable",
            f"item {public_ref} has no launchable route (next_step={step!r})",
        )
    return entrypoint.format(ref=public_ref), remaining


def compose_item_launch_instructions(
    conn: Any,
    parsed: LaunchCreateRequest,
    project_id: int,
    *,
    requester_session_id: str | None = None,
) -> str:
    """Compose the persisted launch body, or keep an explicit full body.

    The origin is derived here the same way the inserted row derives it, so
    the mandate and ``session_launches.origin`` cannot disagree about
    whether this worker is relayed.
    """
    if not parsed.compose_mandate:
        body = parsed.instructions
        if not str(body or "").strip():
            raise SessionLaunchError(
                "payload_invalid",
                "instructions must be non-empty",
            )
        return body
    entrypoint, remaining_legs = _route_for_item(conn, parsed.item, project_id)
    origin = derived_launch_origin(
        conn, session_id=requester_session_id, project_id=project_id
    )
    return compose_single_item_mandate(
        public_ref=parsed.item,
        entrypoint=entrypoint,
        remaining_legs=remaining_legs,
        steering_launched=origin == LAUNCH_ORIGIN_STEERING,
        extras=parsed.instructions,
    )


def launch_request_for_create(
    conn: Any,
    parsed: LaunchCreateRequest,
    *,
    project_id: int,
    session_name: str,
    deadline_seconds: int,
    requester_session_id: str | None = None,
) -> LaunchRequest:
    """Build the domain launch request, composing the mandate when requested."""
    return LaunchRequest(
        project_id=project_id,
        executor_surface=parsed.executor_surface,
        instructions=compose_item_launch_instructions(
            conn, parsed, project_id, requester_session_id=requester_session_id
        ),
        idempotency_key=parsed.idempotency_key,
        sender_surface=parsed.sender_surface,
        machine_id=parsed.machine_id,
        model=parsed.model,
        reasoning_effort=parsed.reasoning_effort,
        context_window_tokens=parsed.context_window_tokens,
        presentation=parsed.presentation,
        session_name=session_name,
        allow_surface_fallback=parsed.allow_surface_fallback,
        deadline_seconds=deadline_seconds,
    )


__all__ = [
    "HEADLESS_LANDING_WAIT_TEACHING",
    "TURN_END_RELAY_TEACHING",
    "compose_item_launch_instructions",
    "compose_single_item_mandate",
    "launch_request_for_create",
]

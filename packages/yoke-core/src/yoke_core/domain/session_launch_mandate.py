"""Server-owned single-item worker mandate composed at launch create."""

from __future__ import annotations

from typing import Any

from yoke_contracts.skill_registry import SKILLS_BY_ID
from yoke_contracts.session_control.models import LaunchCreateRequest
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none
from yoke_core.domain.session_launch_mandate_teaching import STANDING_TEACHINGS
from yoke_core.domain.session_launch_store import marker, value
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.session_workflow_routing import live_next_step
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


_DELIBERATE_CLOSE = (
    "Ending a turn sends no Fleet message. When those legs are complete, "
    "message the orchestrator "
    '(printf %s "DONE {ref} <one-line summary>" | yoke say --stdin '
    "--steering) and END your session — do not pick up further work, do not "
    "chain into other items. Send that report before releasing any claim you "
    "still hold; after a close-out that already released it, --steering "
    "resolves from the item you last held in this session. The PREFIX-N in "
    "the DONE heading is the report identity and must name work this session "
    "holds or released; a repeat of the same DONE is deduplicated rather "
    "than delivered twice. A completion you are later RESUMED to do is its "
    "own leg and reaches the seat on its own, whether or not that resume "
    "hands you a fresh claim — never release an unfinished lane to force "
    "one through. A send answering `Collapsed into an earlier message` did "
    "NOT deliver your body; read it rather than assume you reported. "
    "Complete means the item reached its own terminal status: a close-out "
    "that stopped at a pinned release wait has NOT completed those legs, "
    "and neither the report nor the END is owed yet."
)


def compose_single_item_mandate(
    *,
    public_ref: str,
    entrypoint: str,
    remaining_legs: str,
    extras: str = "",
) -> str:
    """Return the canonical item-bound worker mandate, with optional extras.

    The report target is the steering ROLE, never the launching session.
    Baking a session id in made every mandate outlive its own address: when
    the operator stopped that seat, each later report drove a headless
    resume of a dead session that acknowledged and never answered, and the
    successor seat had to redirect every live worker by hand.

    Every composed mandate belongs to a launched CLI session, which is a
    headless command: it cannot be prompted again inside its own turn, but the
    relay does re-enter it on a delivered message. That is why the landing
    handoff is safe to teach here. The failure it replaces was a worker that
    stopped on the handoff before any notice reached it, leaving its branch
    landed and its item at reviewing-implementation with nobody to close it
    out, seven times in one night; the landing observer's notice is what closes
    that gap, so the mandate names the notice rather than an in-turn wait no
    launched worker survives.

    The release-wait teaching answers the failure this close created. A
    worker whose merge landed at a pinned release wait read "when those legs
    are complete" as complete, so twelve items in one night were reported and
    left unowned before their delivery ran, against four that parked and held.
    The mandate names that boundary so it does not undo the retention.

    The continuation teaching answers the other half of the same fact. A
    headless turn is the whole life of every command it starts, so a turn
    that ends while a long command is still running kills it: two print-mode
    turns ended on a merge their harness had moved to a background task,
    reported success, and left the watcher killed at the turn exit with no
    verdict recorded. Nothing about that hand-back means the work stopped, so
    the mandate says to continue the call rather than to read the hand-back
    as completion.
    """
    close = _DELIBERATE_CLOSE.format(ref=public_ref)
    mandate = (
        f"{entrypoint}\n\n"
        f"Single-item mandate (steering): acquire the {public_ref} work claim "
        f"as your FIRST action — `yoke claims work acquire --item {public_ref} "
        f'--reason "<why you are claiming it>"` — then execute only '
        f"{public_ref} through "
        f"{remaining_legs}. Do NOT create or dispatch any deployment run — "
        "the orchestrator batches deploys. Message the orchestrator ONLY for "
        "substantive updates — a red gate and what failed, a blocker, a conflict "
        "with this instruction, a defect outside your scope, a decision you need. "
        "NEVER send progress: no percentages, elapsed-time polls, watcher "
        'heartbeats, or "still green" notes; relay those in your own output '
        f"instead. {close} If your claim is swept mid-work, reacquire and "
        "continue."
    )
    for teaching in STANDING_TEACHINGS:
        mandate = f"{mandate}\n\n{teaching}"
    extra = extras.strip()
    return f"{mandate}\n\n{extra}" if extra else mandate


def item_entrypoint(next_step: str, public_ref: str) -> str | None:
    """Render the launch command for a bound skill; unlaunchable steps return None."""
    skill = SKILLS_BY_ID.get(next_step)
    return (
        f"{skill.entrypoint} {public_ref}" if skill and skill.kind == "stage" else None
    )


def _route_for_item(conn: Any, public_ref: str, project_id: int) -> tuple[str, str]:
    item_id = resolve_item_ref_or_none(conn, public_ref, project=project_id)
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
    entrypoint = item_entrypoint(str(step or ""), public_ref)
    if not entrypoint:
        raise SessionLaunchError(
            "mandate_unroutable",
            f"item {public_ref} has no launchable route (next_step={step!r})",
        )
    return (
        entrypoint,
        "the remaining legs named by the live workflow bindings through merge/evidence close",
    )


def compose_item_launch_instructions(
    conn: Any,
    parsed: LaunchCreateRequest,
    project_id: int,
) -> str:
    """Compose the persisted launch body, or keep an explicit full body."""
    if not parsed.compose_mandate:
        body = parsed.instructions
        if not str(body or "").strip():
            raise SessionLaunchError(
                "payload_invalid",
                "instructions must be non-empty",
            )
        return body
    public_ref = parsed.item
    if not public_ref:
        raise SessionLaunchError(
            "payload_invalid",
            "composed launches require item",
        )
    entrypoint, remaining_legs = _route_for_item(conn, public_ref, project_id)
    return compose_single_item_mandate(
        public_ref=public_ref,
        entrypoint=entrypoint,
        remaining_legs=remaining_legs,
        extras=parsed.instructions,
    )


def _instructions_for_create(
    conn: Any,
    parsed: LaunchCreateRequest,
    *,
    project_id: int,
    actor_id: int | None,
    session_id: str | None = None,
) -> str:
    """Compose this request's body; skip terminal refuse only for raw replay.

    Composed creates still refuse a terminal item, including same-key
    replay. Raw replay keeps the caller's body so same_request can match
    or conflict without substituting stored text.
    """
    existing = None
    if actor_id is not None:
        from yoke_core.domain.session_launch_store import get_launch_by_dedupe

        existing = get_launch_by_dedupe(conn, actor_id, parsed.idempotency_key)
    if parsed.item and (existing is None or parsed.compose_mandate):
        from yoke_core.domain.session_launch_assignment import (
            refuse_terminal_assigned_item,
        )
        from yoke_core.domain.session_launch_steering_coverage import (
            refuse_uncovered_steering_launch,
        )

        refuse_terminal_assigned_item(
            conn, public_ref=str(parsed.item), project_id=project_id
        )
        refuse_uncovered_steering_launch(
            conn,
            public_ref=str(parsed.item),
            project_id=project_id,
            session_id=session_id,
        )
    return compose_item_launch_instructions(conn, parsed, project_id)


def launch_request_for_create(
    conn: Any,
    parsed: LaunchCreateRequest,
    *,
    project_id: int,
    deadline_seconds: int,
    actor_id: int | None = None,
    session_id: str | None = None,
    session_name: str | None = None,
) -> LaunchRequest:
    """Build the domain launch request, composing the mandate when requested."""
    if session_name is None and parsed.item:
        from yoke_core.domain.session_launch_assignment import assignment_session_name

        session_name = assignment_session_name(
            conn, public_ref=parsed.item, project_id=project_id
        )
    return LaunchRequest(
        project_id=project_id,
        executor_surface=parsed.executor_surface or "",
        instructions=_instructions_for_create(
            conn,
            parsed,
            project_id=project_id,
            actor_id=actor_id,
            session_id=session_id,
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
        item=str(parsed.item) if parsed.item else None,
        level=parsed.level,
    )


__all__ = [
    "compose_item_launch_instructions",
    "compose_single_item_mandate",
    "launch_request_for_create",
    "item_entrypoint",
]

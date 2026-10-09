"""Server-owned single-item worker mandate composed at launch create."""

from __future__ import annotations

from typing import Any

from yoke_contracts.skill_registry import SKILLS_BY_ID
from yoke_contracts.session_control.models import LaunchCreateRequest
from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none
from yoke_core.domain.session_launch_item_level import DEFAULT_LEVEL_REASON
from yoke_core.domain.session_launch_mandate_teaching import LEVEL_HANDOFF_TEACHING
from yoke_core.domain.session_launch_store import marker, value
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.session_workflow_routing import live_next_step
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


_DELIBERATE_CLOSE = (
    "Only at the item's terminal status, send "
    '(printf %s "DONE {ref} <one-line summary>" | yoke say --stdin '
    "--steering) before releasing a claim you still hold, then END your session. "
    "A release wait retains the claim and park; it owes no DONE or END. "
    "Ending a turn sends no Fleet message."
)


def compose_single_item_mandate(
    *,
    public_ref: str,
    entrypoint: str,
    remaining_legs: str,
    extras: str = "",
) -> str:
    """Route one worker to its live skill, with claim and close boundaries.

    Phase instructions own verification, candidate review, landing and delivery
    recovery. The launch carries only what the worker must know before reading
    that skill. Steering is a role address resolved at delivery.
    """
    close = _DELIBERATE_CLOSE.format(ref=public_ref)
    mandate = (
        f"{entrypoint}\n\n"
        f"Single-item mandate: acquire the {public_ref} work claim "
        f"as your FIRST action — `yoke claims work acquire --item {public_ref} "
        f'--reason "<why you are claiming it>"` — then execute only '
        f"{public_ref} through "
        f"{remaining_legs}. Do NOT create or dispatch any deployment run — "
        "the orchestrator batches deploys. Follow the next live bound skill "
        "and read its phase instructions before verification, merge or delivery. "
        "On re-entry, read the Progress Log and lane status/log; preserve existing "
        "work. Before stopping short of done, append a Progress Log checkpoint "
        "with stage, committed and dirty work, and next action. "
        "Send steering only failures, blockers, conflicts, outside-scope defects "
        f"or decisions. Keep progress in your own output. {LEVEL_HANDOFF_TEACHING} {close} "
        "If your claim is swept, reacquire and continue."
    )
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
    from yoke_core.domain.workflow_execution_instructions import resolve_for_item

    item_id = resolve_item_ref_or_none(conn, public_ref, project=project_id)
    instructions = resolve_for_item(conn, int(item_id))
    instruction_text = "\n\n".join(str(row["content"]) for row in instructions)
    mandate = compose_single_item_mandate(
        public_ref=public_ref,
        entrypoint=entrypoint,
        remaining_legs=remaining_legs,
        extras=parsed.instructions,
    )
    return (
        f"Operator execution instructions (obey these):\n{instruction_text}\n\n{mandate}"
        if instruction_text else mandate
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
        level_reason=(
            (parsed.level_reason or DEFAULT_LEVEL_REASON)
            if parsed.item and parsed.level
            else None
        ),
    )


__all__ = [
    "compose_item_launch_instructions",
    "compose_single_item_mandate",
    "launch_request_for_create",
    "item_entrypoint",
]

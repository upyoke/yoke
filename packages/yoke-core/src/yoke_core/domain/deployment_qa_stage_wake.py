"""Wake whoever a deployment run's waiting QA stage is owed to.

An item-scoped stage wakes that member's claim holder (or the project's
steering seat, when the claim holder is gone); a run-scoped stage has no
single member to address, so it wakes the project's deploy-lock driver
instead — the same "one driver per project" concept
:mod:`yoke_core.domain.deploy_lock` already serializes run creation and
execution against. The item-scoped branch reuses
:mod:`yoke_core.domain.merge_queue_landing_notice`'s recipient/delivery
primitives; the run-scoped steering fallback reuses
:mod:`yoke_core.domain.steering_scope_coverage`'s scope-aware seat rule
rather than picking whichever steering claim on the project is newest —
a project can carry more than one live steering seat at once, each scoped
to a different strategy document, and run-scoped work carries no document
of its own to disambiguate among them. Addressing the project's plain,
undocumented scope only ever matches a seat covering unlinked work, so a
project whose only live seat is narrowed to one document correctly finds
nobody rather than guessing — the wait still shows in the stage's own
diagnostic either way.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.merge_queue_landing_notice import HOLDER, STEERING, push_notice

#: The project's deploy-lock holder answered for a run-scoped wait.
DRIVER = "driver"


def stage_wait_idempotency_key(
    run_id: str, stage_name: str, item_id: int, target_digest: str = ""
) -> str:
    """One notice per run/stage/item/attempt.

    ``target_digest`` is the stage's own pinned-target identity
    (:func:`deployment_qa_stage_gate.deployment_qa_stage_status`'s
    ``target_digest``): stable across every recheck of the SAME wait, and
    different when the pinned target changes within the stage's existing
    retry/requirement contract. Folding it in means a genuinely distinct
    attempt gets its own notice instead of being silently absorbed by an
    earlier wait's key -- it does not authorize swapping a frozen run's
    candidate; that stays a replacement run's job.
    """
    return f"deployment-qa-stage-wait:{run_id}:{stage_name}:{item_id}:{target_digest}"


def run_stage_wait_idempotency_key(
    run_id: str, stage_name: str, target_digest: str = ""
) -> str:
    """One notice per run/stage/attempt, mirroring the item-scoped key."""
    return f"deployment-qa-stage-wait:{run_id}:{stage_name}:run:{target_digest}"


def _execution_context(*, target_tier: str, revision: str) -> str:
    """Name the configured target and revision a wait's evidence is against.

    Rendered once into the notice body rather than left to a live status
    lookup, because these two facts are frozen for the run's whole life and
    do not go stale the way a computed "still needed" reason can.
    """
    target = target_tier or "an unspecified target"
    rev = (revision or "")[:12] or "an unresolved revision"
    return f"{target} at {rev}"


def _plan_selection(names_cases: bool) -> str:
    """The ``--plan`` fragment a wake's run recipe may or may not carry.

    ``--plan`` selects cases for a stage that names none. A stage that
    already names its own -- pinned, frozen, attached, admitted, or
    directly authored -- would materialize a second, duplicate set of
    obligations beside the ones it credits, so its recipe omits the flag
    entirely rather than printing one the command now refuses.
    """
    return "" if names_cases else " --plan PLAN"


def stage_wait_message(
    *,
    run_id: str,
    stage_name: str,
    item_ref: str,
    target_tier: str,
    revision: str,
    reasons: str,
    route: str,
    names_cases: bool,
) -> str:
    """Name the run, stage, target/revision, item, and who this reaches.

    ``reasons`` is delivered only on the first check that finds this wait
    (later checks reuse the same idempotency key), so the surrounding
    sentence stays true on its own even if ``reasons`` reads stale by the
    time it is read; the status lookup command covers the rest.
    """
    context = _execution_context(target_tier=target_tier, revision=revision)
    addressed = (
        f"{item_ref}'s claim holder"
        if route == HOLDER
        else f"{item_ref}'s project steering seat (its claim holder is gone)"
    )
    return (
        f"Deployment run {run_id} reached item-scoped QA stage {stage_name!r} "
        f"for {context}. Reaching {addressed}: {item_ref} still needs to "
        f"supply this stage's evidence/verdict ({reasons}). Run its cases "
        "naming BOTH the stage and the member, which is what this stage "
        f"credits: 'yoke qa plan run --deployment-run-id {run_id} --stage "
        f"{stage_name} --member {item_ref}{_plan_selection(names_cases)} "
        "--project PROJECT'. "
        "Omitting them materializes requirements this stage never counts, so "
        "the verdict would discharge nothing. The stage binds the run's own "
        "deployed target, so a plan authored before this release still "
        f"verifies it. Check 'yoke deployment-runs get {run_id}' for the "
        "current state."
    )


def run_stage_wait_message(
    *,
    run_id: str,
    stage_name: str,
    target_tier: str,
    revision: str,
    reasons: str,
    route: str,
    names_cases: bool,
) -> str:
    """The run-scoped counterpart to :func:`stage_wait_message`."""
    context = _execution_context(target_tier=target_tier, revision=revision)
    addressed = (
        "its deploy-lock driver"
        if route == DRIVER
        else "the project's steering seat (no session holds its deploy lock)"
    )
    return (
        f"Deployment run {run_id} reached run-scoped QA stage {stage_name!r} "
        f"for {context}. Reaching {addressed}: the stage still needs "
        f"evidence/verdict ({reasons}). Run its cases naming the stage, "
        "which is what this stage credits: 'yoke qa plan run "
        f"--deployment-run-id {run_id} --stage {stage_name}"
        f"{_plan_selection(names_cases)} "
        f"--project PROJECT'. Check 'yoke deployment-runs get {run_id}' for "
        "the current state."
    )


def notify_item_scoped_qa_wait(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    item_id: int,
    project_id: int,
    reasons: str,
    names_cases: bool,
    target_tier: str = "",
    revision: str = "",
    target_digest: str = "",
    now: Optional[datetime] = None,
) -> str:
    """Wake the item's claim holder (or steering) that its QA stage is waiting.

    ``""`` means nobody was addressable, ``"undelivered"`` means queued but
    not yet reached, ``"delivered"`` means it reached the recipient —
    matching :func:`push_notice`'s own contract. The idempotency key is
    stable per (run, stage, item, target_digest), so a stage rechecked on
    every pipeline retry sends exactly one notice per distinct wait; a new
    deploy attempt (a new ``run_id``) or a distinct pinned target within
    the stage's own existing retry/requirement contract (a new
    ``target_digest``) is always a fresh key.
    """
    from yoke_core.domain.project_identity import render_item_ref

    item_ref = render_item_ref(conn, int(item_id))
    return push_notice(
        conn,
        item_id=item_id,
        project_id=project_id,
        body_for_route=lambda route: stage_wait_message(
            run_id=run_id,
            stage_name=stage_name,
            item_ref=item_ref,
            target_tier=target_tier,
            revision=revision,
            reasons=reasons,
            route=route,
            names_cases=names_cases,
        ),
        idempotency_key=stage_wait_idempotency_key(
            run_id, stage_name, item_id, target_digest
        ),
        now=now or datetime.now(timezone.utc),
    )


def resolve_run_driver_recipient(
    conn: Any, *, project_id: int
) -> tuple[str, int, str]:
    """The project's live deploy-lock holder, else its undocumented steering seat.

    The steering fallback addresses the project's plain scope (no
    ``document`` key) through :func:`steering_scope_coverage.covering_seat`,
    the same rule item-scoped role addressing already uses for unlinked
    work — a document-narrowed seat (e.g. one scoped to a release-planning
    doc) does not cover it, so a project with only such a seat live
    correctly resolves to nobody rather than an arbitrary "newest claim."
    ``("", 0, "")`` means nobody is addressable at all.
    """
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.project_identity import resolve_project
    from yoke_core.domain.steering_scope_coverage import PROJECT_KEY, covering_seat
    from yoke_core.domain.work_claim_targets import make_deploy_serialization_target

    identity = resolve_project(conn, project_id, required=False)
    if identity is not None:
        claim = active_claim(
            conn, make_deploy_serialization_target(identity.id, identity.slug)
        )
        if claim is not None and claim.actor_id is not None:
            return claim.session_id, int(claim.actor_id), DRIVER
    seat = covering_seat(conn, {PROJECT_KEY: int(project_id)})
    if seat is None or seat.get("actor_id") is None:
        return "", 0, ""
    return str(seat["session_id"]), int(seat["actor_id"]), STEERING


def _receipt_delivered(conn: Any, message_id: str, session_id: str) -> bool:
    """True when the recipient actually received the envelope, not merely queued."""
    from yoke_core.domain.session_message_store import message_details

    details = message_details(conn, message_id)
    for recipient in details.get("recipients") or ():
        if str(recipient.get("session_id") or "") != session_id:
            continue
        if recipient.get("last_injected_at") or recipient.get("acknowledged_at"):
            return True
        if int(recipient.get("injection_count") or 0) > 0:
            return True
        return str(recipient.get("state") or "") in {"injected", "acknowledged"}
    return False


def push_run_scoped_notice(
    conn: Any,
    *,
    project_id: int,
    body_for_route: Callable[[str], str],
    idempotency_key: str,
    now: Optional[datetime] = None,
) -> str:
    """Reach whoever is driving a project's release, and say whether it landed.

    The run-scoped counterpart to
    :func:`merge_queue_landing_notice.push_notice`, with the same return
    contract: ``""`` nobody addressable, ``"undelivered"`` queued but not
    yet reached, ``"delivered"`` reached the recipient. ``body_for_route``
    is passed the route that found the recipient so the body can name who
    it reached.
    """
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
    from yoke_core.domain.session_message_service import send_message

    session_id, actor_id, route = resolve_run_driver_recipient(
        conn, project_id=project_id
    )
    if not session_id:
        return ""
    created = send_message(
        conn,
        actor_id=actor_id,
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[session_id]),
        body=body_for_route(route),
        idempotency_key=idempotency_key,
        idempotency_intent_only=True,
        now=now or datetime.now(timezone.utc),
        commit=False,
    )
    message_id = str(created["message_id"])
    mark_explicit_stopped_wake(conn, message_id=message_id, session_id=session_id)
    return (
        "delivered"
        if _receipt_delivered(conn, message_id, session_id)
        else "undelivered"
    )


def notify_run_scoped_qa_wait(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    project_id: int,
    reasons: str,
    names_cases: bool,
    target_tier: str = "",
    revision: str = "",
    target_digest: str = "",
    now: Optional[datetime] = None,
) -> str:
    """Wake the project's deploy-lock driver (or steering) for a run-scoped wait.

    Same contract as :func:`notify_item_scoped_qa_wait`, addressed to
    whoever is driving the release instead of an attached item.
    """
    return push_run_scoped_notice(
        conn,
        project_id=project_id,
        body_for_route=lambda route: run_stage_wait_message(
            run_id=run_id,
            stage_name=stage_name,
            target_tier=target_tier,
            revision=revision,
            reasons=reasons,
            route=route,
            names_cases=names_cases,
        ),
        idempotency_key=run_stage_wait_idempotency_key(
            run_id, stage_name, target_digest
        ),
        now=now,
    )


__all__ = [
    "DRIVER",
    "notify_item_scoped_qa_wait",
    "notify_run_scoped_qa_wait",
    "push_run_scoped_notice",
    "resolve_run_driver_recipient",
    "run_stage_wait_idempotency_key",
    "run_stage_wait_message",
    "stage_wait_idempotency_key",
    "stage_wait_message",
]

"""Wake whoever a deployment run's waiting QA stage is owed to.

An item-scoped stage wakes that member's claim holder (or the project's
steering seat, when the claim holder is gone); a run-scoped stage has no
single member to address, so it wakes the project's deploy-lock driver
instead. The item-scoped branch reuses
:mod:`yoke_core.domain.merge_queue_landing_notice`'s recipient/delivery
primitives; the run-scoped branch reuses
:mod:`yoke_core.domain.deployment_run_driver_notice`, which owns the
driver-or-steering recipient rule and the delivery contract every
run-scoped wait shares. A wait nobody is addressable for still shows in
the stage's own diagnostic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.domain.deployment_run_driver_notice import (
    DRIVER,
    push_run_scoped_notice,
)
from yoke_core.domain.merge_queue_landing_notice import HOLDER, push_notice

#: Identity every item-scoped and run-scoped QA wait notice shares, so a
#: later reader can find every still-pending wait without parsing bodies.
DEPLOYMENT_QA_STAGE_WAIT_PREFIX = "deployment-qa-stage-wait:"

#: The member slot a run-scoped wait stores instead of an item id.
RUN_SCOPED_WAIT_TOKEN = "run"


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
    return (
        f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:{stage_name}:"
        f"{item_id}:{target_digest}"
    )


def run_stage_wait_idempotency_key(
    run_id: str, stage_name: str, target_digest: str = ""
) -> str:
    """One notice per run/stage/attempt, mirroring the item-scoped key."""
    return (
        f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:{stage_name}:"
        f"{RUN_SCOPED_WAIT_TOKEN}:{target_digest}"
    )


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
    discharge: str | None = None,
) -> str:
    """Name the run, stage, target/revision, item, and who this reaches.

    ``reasons`` is delivered only on the first check that finds this wait
    (later checks reuse the same idempotency key), so the surrounding
    sentence stays true on its own even if ``reasons`` reads stale by the
    time it is read; the status lookup command covers the rest.

    ``discharge`` is the recorded no-obligation (or waiver-backed none)
    statement. When it is set, this member has nothing to run, so the
    body names that fact instead of handing ``yoke qa plan run``.
    """
    context = _execution_context(target_tier=target_tier, revision=revision)
    addressed = (
        f"{item_ref}'s claim holder"
        if route == HOLDER
        else f"{item_ref}'s project steering seat (its claim holder is gone)"
    )
    if discharge:
        return (
            f"Deployment run {run_id} reached item-scoped QA stage "
            f"{stage_name!r} for {context}. Reaching {addressed}: "
            f"{discharge} Check 'yoke deployment-runs get {run_id}' for "
            "the current state."
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
    from yoke_core.domain.qa_plan_empty_roster import member_discharge_statement

    item_ref = render_item_ref(conn, int(item_id))
    discharge = member_discharge_statement(conn, int(item_id))
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
            discharge=discharge,
        ),
        idempotency_key=stage_wait_idempotency_key(
            run_id, stage_name, item_id, target_digest
        ),
        now=now or datetime.now(timezone.utc),
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
    "DEPLOYMENT_QA_STAGE_WAIT_PREFIX",
    "RUN_SCOPED_WAIT_TOKEN",
    "notify_item_scoped_qa_wait",
    "notify_run_scoped_qa_wait",
    "run_stage_wait_idempotency_key",
    "run_stage_wait_message",
    "stage_wait_idempotency_key",
    "stage_wait_message",
]

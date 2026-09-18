"""Attaching one executable QA case straight to a deployment run.

A release's own checks used to be authorable only by the pipeline that
materializes them from a frozen plan snapshot, so a person who wanted to
record one more check against a run in flight had no product surface at all
— the same act was one command away on an item. This is that surface, and
it is deliberately the same function id, the same claim policy, and the same
row shape as item-attached authoring rather than a second QA model.

What it refuses, and why each refusal names its recovery:

* a run that has already finished — its evidence is closed, and a case
  added afterwards would read as proof of something nobody ran;
* a stage the run's own pinned flow does not declare, or a member item the
  run does not carry — a case whose target does not exist cannot be
  executed, and a run whose composition is frozen is not renegotiated here;
* a member without a stage — storage models a member check as a check at a
  stage, and the subject constraint rejects the half-named shape;
* a member the run does not carry, named back with the ones it does;
* a case with no method — what distinguishes a case from a bookkeeping row
  is that something can execute it, and only the run's own pipeline writes
  the materialized acceptance kinds;
* a case with no bindable target — name the frozen QA stage (and wait for
  its source-stage receipt) or a registered ``--target-env``, because an
  unbound row cannot execute and is not a silent admission.

It writes the same execution-target fields plan materialization writes, so
a hand-authored run/stage/member case is executable against that frozen
destination rather than an inert row the executor cannot repair.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.handlers.qa import _error, _p
from yoke_core.domain.handlers.qa_requirement_insert import (
    INSERT_SQL,
    RequirementSubject,
    insert_params,
)
from yoke_core.domain.handlers.qa_requirement_method_validation import (
    validate_method_requirement,
)
from yoke_core.domain.handlers.qa_requirement_row_validation import validate_row
from yoke_core.domain.json_helper import loads_text


#: A run in one of these states has recorded its outcome. Adding a case to
#: one cannot change what happened, so the surface says so rather than
#: storing a case that will never run.
CLOSED_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


def _run_row(conn: Any, run_id: str) -> Optional[Any]:
    return conn.execute(
        "SELECT dr.id, dr.status, dr.project_id, df.stages "
        "FROM deployment_runs dr JOIN deployment_flows df ON df.id=dr.flow "
        f"WHERE dr.id={_p(conn)}",
        (run_id,),
    ).fetchone()


def _stage_names(stages_json: Any) -> list[str]:
    try:
        stages = loads_text(str(stages_json or "[]"))
    except (TypeError, ValueError):
        return []
    return [
        str(stage.get("name") or "")
        for stage in stages
        if isinstance(stage, dict) and stage.get("name")
    ]


def _members(conn: Any, run_id: str) -> list[tuple[int, str]]:
    """This run's member items as ``(item_id, public ref)`` pairs."""
    rows = conn.execute(
        "SELECT i.id, i.project_sequence, p.slug, p.public_item_prefix "
        "FROM deployment_run_items dri JOIN items i ON i.id=dri.item_id "
        "JOIN projects p ON p.id=i.project_id "
        f"WHERE dri.run_id={_p(conn)} ORDER BY i.id",
        (run_id,),
    ).fetchall()
    return [
        (
            int(row["id"]),
            format_item_ref(
                row["slug"], row["public_item_prefix"], row["project_sequence"]
            ),
        )
        for row in rows
    ]


def _match_member(members: list[tuple[int, str]], ref: str) -> Optional[int]:
    """Resolve an operator's token against exactly this run's membership.

    A person names a member the way they read it — ``PREFIX-N`` — while the
    row stores the internal id. Matching inside the run's own membership
    answers both without a second resolver, and a token that matches
    nothing is a composition fact the refusal can state precisely.
    """
    token = ref.strip()
    for item_id, public_ref in members:
        if token == public_ref or token == str(item_id):
            return item_id
    return None


def _validate_run_subject(
    conn: Any,
    *,
    run_id: str,
    stage: Optional[str],
    member_ref: Optional[str],
) -> tuple[Optional[RequirementSubject], Optional[HandlerOutcome]]:
    run = _run_row(conn, run_id)
    if run is None:
        return None, _error(
            "not_found",
            f"deployment run {run_id!r} not found; list runs with "
            "`yoke deployment-runs list --project P`",
            jsonpath="$.target.deployment_run_id",
        )
    status = str(run["status"] or "")
    if status in CLOSED_RUN_STATUSES:
        return None, _error(
            "precondition_failed",
            f"deployment run {run_id!r} is {status}; its QA evidence is "
            "closed. Attach the case to a new run, or to the item whose "
            "verification it belongs to.",
            jsonpath="$.target.deployment_run_id",
        )
    if member_ref is not None and stage is None:
        return None, _error(
            "payload_invalid",
            "deployment_member_item names a check at a stage, so "
            "deployment_stage is required with it",
            jsonpath="$.payload.deployment_stage",
        )
    if stage is not None:
        names = _stage_names(run["stages"])
        if stage not in names:
            return None, _error(
                "payload_invalid",
                f"deployment run {run_id!r} declares no stage {stage!r}; "
                f"its stages are {', '.join(names) or 'none'}",
                jsonpath="$.payload.deployment_stage",
            )
    resolved_member: Optional[int] = None
    if member_ref is not None:
        members = _members(conn, run_id)
        resolved_member = _match_member(members, member_ref)
        if resolved_member is None:
            carried = ", ".join(ref for _, ref in members) or "no items"
            return None, _error(
                "payload_invalid",
                f"deployment run {run_id!r} does not carry {member_ref!r}; "
                f"it carries {carried}. Run composition is frozen at start "
                "and is not widened by attaching a case.",
                jsonpath="$.payload.deployment_member_item",
            )
    return (
        RequirementSubject(
            deployment_run_id=run_id,
            deployment_stage=stage,
            deployment_member_item_id=resolved_member,
        ),
        None,
    )


def handle_deployment_run_requirement_add(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Insert one run-attached executable case and return its identity."""
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    run_id = str(request.target.deployment_run_id or "").strip()
    if not run_id:
        return _error(
            "target_invalid",
            "qa.requirement.add with target.kind='deployment_run' requires "
            "target.deployment_run_id",
            jsonpath="$.target.deployment_run_id",
        )
    row = dict(request.payload or {})
    stage = row.pop("deployment_stage", None)
    member_ref = row.pop("deployment_member_item", None)
    if row.pop("workflow_transition_id", None) is not None:
        return _error(
            "payload_invalid",
            "a run-attached case is governed by its deployment run, not by "
            "an item workflow stage; omit workflow_transition_id",
            jsonpath="$.payload.workflow_transition_id",
        )
    if not str(row.get("method_id") or "").strip():
        return _error(
            "payload_invalid",
            "a run-attached case must name the registered method that "
            "executes it (--method-id); the plan-materialized kinds are "
            "written by the run's own pipeline",
            jsonpath="$.payload.method_id",
        )
    invalid = validate_row(row, "$.payload")
    if invalid is not None:
        return invalid

    conn = connect()
    try:
        subject, invalid = _validate_run_subject(
            conn,
            run_id=run_id,
            stage=None if stage is None else str(stage),
            member_ref=None if member_ref is None else str(member_ref),
        )
        if invalid is not None:
            return invalid
        invalid = validate_method_requirement(conn, row, "$.payload")
        if invalid is not None:
            return invalid
        from yoke_core.domain.deployment_qa_direct_case_target import (
            bind_authored_deployment_requirement,
        )

        refused = bind_authored_deployment_requirement(
            conn,
            run_id=run_id,
            stage=subject.deployment_stage,
            member_item_id=subject.deployment_member_item_id,
            row=row,
        )
        if refused:
            return _error(
                "payload_invalid",
                refused,
                jsonpath="$.payload.deployment_stage",
            )
        cur = conn.execute(
            INSERT_SQL.format(p=_p(conn)),
            insert_params(subject, row, iso8601_now()),
        )
        inserted_id = int(cur.fetchone()[0])
        conn.commit()
        emit_qa_requirement_event(
            conn,
            db_path=None,
            event_name="QARequirementCreated",
            requirement_id=inserted_id,
            qa_kind=row["qa_kind"],
            qa_phase=row["qa_phase"],
            target_row={
                "item_id": None,
                "epic_id": None,
                "task_num": None,
                "deployment_run_id": run_id,
            },
        )
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_id": inserted_id,
            "deployment_run_id": run_id,
            "deployment_stage": subject.deployment_stage,
            "deployment_member_item_id": subject.deployment_member_item_id,
        },
        primary_success=True,
    )


__all__ = [
    "CLOSED_RUN_STATUSES",
    "handle_deployment_run_requirement_add",
]

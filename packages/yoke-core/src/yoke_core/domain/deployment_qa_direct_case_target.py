"""Bind an executable target onto a hand-authored deployment QA case.

Plan materialization already freezes the run/stage/member destination through
:func:`deployment_qa_execution_target`. Direct authoring used to skip that
write, so the row could not execute and the executor named a plan repair that
does not exist for this shape. This module is that same authority, used at
create, at stage materialization, and at execute-time recovery.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_admission_materialization import (
    ADMITTED_REQUIREMENT_CASE_PREFIX,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.qa_environment_execution_target import (
    apply_named_target_to_requirement_row,
    persist_requirement_target_snapshot,
)
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    canonical_target,
    target_digest,
)


INCOMPLETE_TARGET_REPAIR = (
    "a run-attached executable case needs a bindable target: name "
    "--deployment-stage so the frozen run/stage authority can bind, or "
    "--target-env for a registered environment of this project"
)

MISSING_DIRECT_TARGET_REPAIR = (
    "this direct deployment QA case has no execution target; re-run "
    "`yoke qa case run --requirement-id N` after the QA stage's source "
    "stage has a ready receipt. Do not add the member to the run "
    "(composition is frozen) and do not attach a plan to bind the target."
)


def _environment_name(target: Mapping[str, Any]) -> str | None:
    environment = target.get("environment")
    if not isinstance(environment, Mapping):
        return None
    name = str(environment.get("name") or "").strip()
    return name or None


def _run_project_id(conn: Any, run_id: str) -> int | None:
    row = conn.execute(
        "SELECT project_id FROM deployment_runs WHERE id=%s",
        (str(run_id),),
    ).fetchone()
    if row is None or row["project_id"] is None:
        return None
    return int(row["project_id"])


def resolve_frozen_deployment_case_target(
    conn: Any,
    *,
    run_id: str,
    stage: str,
    member_item_id: int | None,
) -> dict[str, Any]:
    """Return the immutable destination the pinned QA stage currently names."""
    subject = deployment_qa_stage_subject(
        conn,
        run_id=str(run_id),
        stage_name=str(stage),
        member_item_id=member_item_id,
    )
    return deployment_qa_execution_target(conn, subject)


def _apply_target(row: dict[str, Any], target: Mapping[str, Any]) -> None:
    row["execution_target_json"] = canonical_target(target)
    row["execution_target_digest"] = target_digest(target)
    named = _environment_name(target)
    if named and not str(row.get("target_env") or "").strip():
        row["target_env"] = named


def bind_authored_deployment_requirement(
    conn: Any,
    *,
    run_id: str,
    stage: str | None,
    member_item_id: int | None,
    row: dict[str, Any],
) -> str:
    """Fill target columns on an about-to-insert row; return a refusal or ''."""
    named = str(row.get("target_env") or "").strip()
    if stage:
        try:
            target = resolve_frozen_deployment_case_target(
                conn,
                run_id=str(run_id),
                stage=str(stage),
                member_item_id=member_item_id,
            )
        except (LookupError, TypeError, ValueError) as exc:
            if not named:
                return (
                    f"{exc}. Recovery: attach the case to a deployment QA stage "
                    "after its source stage has a ready receipt, or name "
                    "--target-env for a registered environment of this project."
                )
            project_id = _run_project_id(conn, run_id)
            if project_id is None:
                return "requirement has no project to resolve an execution target against"
            try:
                apply_named_target_to_requirement_row(
                    conn, project_id=int(project_id), row=row
                )
            except QaExecutionTargetError as named_exc:
                return str(named_exc)
            if not row.get("execution_target_digest"):
                return (
                    f"{exc}. Environment {named!r} is not yet bindable; record "
                    "its reviewable URL, or wait for the QA stage receipt."
                )
            return ""
        frozen_env = _environment_name(target)
        if named and frozen_env and named != frozen_env:
            return (
                f"case names environment {named!r}, but frozen stage "
                f"{stage!r} targets {frozen_env!r}; omit --target-env or "
                "name the stage's own environment"
            )
        _apply_target(row, target)
        return ""
    if not named:
        return INCOMPLETE_TARGET_REPAIR
    project_id = _run_project_id(conn, run_id)
    if project_id is None:
        return "requirement has no project to resolve an execution target against"
    try:
        apply_named_target_to_requirement_row(
            conn, project_id=int(project_id), row=row
        )
    except QaExecutionTargetError as exc:
        return str(exc)
    if not row.get("execution_target_digest"):
        return (
            f"environment {named!r} is not yet bindable on this project; "
            "record its reviewable URL under hosts.app, or name "
            "--deployment-stage so frozen run/stage authority can bind"
        )
    return ""


def list_direct_deployment_method_cases(
    conn: Any,
    *,
    run_id: str,
    stage: str,
    member_item_id: int | None,
) -> list[dict[str, Any]]:
    """Plan-less method cases on this stage subject, excluding admitted copies."""
    return query_rows(
        conn,
        "SELECT id,execution_target_json,execution_target_digest,plan_case_key,"
        "target_env "
        "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s AND plan_id IS NULL "
        "AND method_id IS NOT NULL AND waived_at IS NULL "
        "AND (plan_case_key IS NULL OR plan_case_key NOT LIKE %s) "
        "ORDER BY id",
        (
            str(run_id),
            str(stage),
            member_item_id or 0,
            f"{ADMITTED_REQUIREMENT_CASE_PREFIX}%",
        ),
    )


def bind_existing_direct_deployment_cases(
    conn: Any,
    *,
    subject: Mapping[str, Any],
    target: Mapping[str, Any],
) -> list[int]:
    """Idempotently stamp the frozen target onto unbound direct cases."""
    bound: list[int] = []
    expected = target_digest(target)
    env_name = _environment_name(target)
    for row in list_direct_deployment_method_cases(
        conn,
        run_id=str(subject["id"]),
        stage=str(subject["stage"]["name"]),
        member_item_id=subject.get("member_item_id"),
    ):
        current = str(row["execution_target_digest"] or "")
        if current and current != expected:
            continue
        if current == expected:
            bound.append(int(row["id"]))
            continue
        payload = {
            "execution_target_json": canonical_target(target),
            "execution_target_digest": expected,
        }
        persist_requirement_target_snapshot(conn, int(row["id"]), payload)
        if env_name and not str(row.get("target_env") or "").strip():
            conn.execute(
                "UPDATE qa_requirements SET target_env=%s WHERE id=%s "
                "AND (target_env IS NULL OR target_env='')",
                (env_name, int(row["id"])),
            )
        bound.append(int(row["id"]))
    return bound


def bind_missing_deployment_case_target(
    conn: Any, row: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Persist and return the frozen target for one unbound direct case."""
    stage = str(row["deployment_stage"] or "").strip()
    run_id = str(row["deployment_run_id"] or "").strip()
    if not stage or not run_id:
        return None
    member = row["deployment_member_item_id"]
    target = resolve_frozen_deployment_case_target(
        conn,
        run_id=run_id,
        stage=stage,
        member_item_id=int(member) if member is not None else None,
    )
    persist_requirement_target_snapshot(
        conn,
        int(row["requirement_id"]),
        {
            "execution_target_json": canonical_target(target),
            "execution_target_digest": target_digest(target),
        },
    )
    return {"target": dict(target), "digest": target_digest(target)}


def restore_missing_deployment_case_target(
    conn: Any, row: Mapping[str, Any], context: dict[str, Any]
) -> None:
    """Stamp the frozen destination onto an unbound case and its runner context."""
    from yoke_core.domain.qa_execution_environment_target import (
        require_case_target,
        require_runtime_target,
    )

    try:
        bound = bind_missing_deployment_case_target(conn, row)
    except (LookupError, TypeError, ValueError) as exc:
        raise ValueError(f"{MISSING_DIRECT_TARGET_REPAIR} ({exc})") from exc
    if bound is None:
        raise ValueError(MISSING_DIRECT_TARGET_REPAIR)
    require_runtime_target(bound["target"])
    require_case_target(context, bound["target"])
    context["execution_target"] = bound["target"]
    context["execution_target_digest"] = bound["digest"]


__all__ = [
    "INCOMPLETE_TARGET_REPAIR",
    "MISSING_DIRECT_TARGET_REPAIR",
    "bind_authored_deployment_requirement",
    "bind_existing_direct_deployment_cases",
    "bind_missing_deployment_case_target",
    "list_direct_deployment_method_cases",
    "resolve_frozen_deployment_case_target",
    "restore_missing_deployment_case_target",
]

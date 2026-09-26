"""Resolve a deployment QA function's frozen stage and member authority."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.function_target_row_project import (
    resolve_deployment_run_project,
    slug_for_project_id,
)
from yoke_core.domain.project_identity import resolve_item_id, resolve_project_id


class QaSubjectProjectError(ValueError):
    """A QA write does not name the project of its verified subject."""


SCOPED_RUN_FUNCTIONS = frozenset(
    {
        "qa.browser_context.get",
        "qa.requirement.add",
        "qa.plan.materialize",
        "qa.plan.rematerialize",
        "qa.plan_execution.begin",
        "qa.plan_execution.heartbeat",
        "qa.plan_execution.advance",
        "qa.plan_execution.complete",
        "qa.plan_execution.abort",
        "qa.plan_review.begin",
        "qa.plan_review.submit",
    }
)


def _execution_subject(
    conn: Any, execution_id: str
) -> tuple[str, str | None, int | None]:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT deployment_run_id,deployment_stage,deployment_member_item_id "
        f"FROM qa_plan_executions WHERE id={marker}",
        (execution_id,),
    ).fetchone()
    if row is None:
        raise QaSubjectProjectError(
            f"QA plan execution {execution_id!r} was not found; begin the stage "
            "execution again before recording its result"
        )
    return str(row[0] or ""), row[1], int(row[2]) if row[2] is not None else None


def resolve_run_qa_subject(
    conn: Any, request: FunctionCallRequest
) -> tuple[int, str, int | None]:
    """Return (project, slug, member) from the run's real QA subject.

    The execution row owns the subject after begin. For materialization and
    begin, the pinned stage and frozen membership own it. An explicit project
    is only a consistency hint; it never chooses authorization authority.
    """
    run_id = str(request.target.deployment_run_id or "")
    if not run_id:
        raise QaSubjectProjectError("deployment QA requires a deployment run id")
    payload = request.payload or {}
    execution_id = str(payload.get("execution_id") or "")
    if request.function == "qa.browser_context.get":
        requirement_id = payload.get("requirement_id")
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT deployment_run_id,deployment_stage,deployment_member_item_id "
            f"FROM qa_requirements WHERE id={marker}",
            (requirement_id,),
        ).fetchone()
        if row is None or str(row[0] or "") != run_id:
            raise QaSubjectProjectError(
                f"QA requirement {requirement_id!r} does not belong to run "
                f"{run_id!r}; use its recorded run and project"
            )
        stage = row[1]
        member_id = int(row[2]) if row[2] is not None else None
    elif execution_id:
        execution_run, stage, member_id = _execution_subject(conn, execution_id)
        if execution_run != run_id:
            raise QaSubjectProjectError(
                f"QA plan execution {execution_id!r} belongs to another run; "
                "use its recorded deployment run id"
            )
    else:
        stage = payload.get("deployment_stage")
        member_ref = payload.get("deployment_member") or payload.get(
            "deployment_member_item"
        )
        member_id = None
        if member_ref:
            try:
                member_id = (
                    int(member_ref)
                    if payload.get("deployment_member_item")
                    and str(member_ref).isdigit()
                    else resolve_item_id(conn, str(member_ref))
                )
            except LookupError as exc:
                raise QaSubjectProjectError(
                    f"deployment member {member_ref!r} was not found; name a "
                    "member item attached to this run"
                ) from exc
            if member_id is None:
                raise QaSubjectProjectError(
                    f"deployment member {member_ref!r} was not found; name a "
                    "member item attached to this run"
                )
    if member_id is not None and not stage:
        raise QaSubjectProjectError(
            "deployment member requires a pinned QA stage; pass --stage"
        )
    if stage:
        try:
            subject = deployment_qa_stage_subject(
                conn,
                run_id=run_id,
                stage_name=str(stage),
                member_item_id=member_id,
            )
        except (LookupError, ValueError) as exc:
            raise QaSubjectProjectError(
                f"deployment QA subject is unavailable: {exc}; use the active "
                "run stage and an attached member, then retry"
            ) from exc
        project_id = int(subject.get("member_project_id") or subject["project_id"])
        slug = slug_for_project_id(conn, project_id)
    else:
        run_project = resolve_deployment_run_project(conn, run_id)
        if run_project is None:
            raise QaSubjectProjectError(
                f"deployment run {run_id!r} was not found; check the run id"
            )
        project_id, slug = run_project
    for hint in (request.target.project_id, payload.get("project")):
        if not hint:
            continue
        try:
            hinted_id = resolve_project_id(conn, str(hint))
        except LookupError as exc:
            raise QaSubjectProjectError(
                f"QA project hint {hint!r} was not found; use --project {slug}"
            ) from exc
        if hinted_id != project_id:
            raise QaSubjectProjectError(
                f"QA project hint {hint!r} does not match subject project "
                f"{slug!r}; use --project {slug}"
            )
    return project_id, slug, member_id


def bound_target_project_for_member(
    conn: Any, target: dict[str, Any], member_project_id: int, requirement_id: int
) -> int | None:
    """Allow a member's Browser case to inspect its run's deployed host."""
    deployment = target.get("deployment")
    project = target.get("project")
    if not isinstance(deployment, dict) or not isinstance(project, dict):
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT deployment_run_id,deployment_stage,deployment_member_item_id "
        f"FROM qa_requirements WHERE id={marker}",
        (requirement_id,),
    ).fetchone()
    try:
        matching = row is not None and (
            str(row[0] or "") == str(deployment.get("run_id") or "")
            and str(row[1] or "") == str(deployment.get("stage") or "")
            and row[2] is not None
            and int(row[2]) == int(deployment.get("member_item_id") or 0)
        )
    except (TypeError, ValueError):
        matching = False
    if not matching:
        return None
    try:
        subject = deployment_qa_stage_subject(
            conn,
            run_id=str(deployment["run_id"]),
            stage_name=str(deployment["stage"]),
            member_item_id=int(deployment["member_item_id"]),
            require_active=False,
        )
        host_id = int(project["id"])
    except (KeyError, TypeError, ValueError, LookupError):
        return None
    if (
        int(subject["member_project_id"]) != int(member_project_id)
        or int(subject["project_id"]) != host_id
    ):
        return None
    return host_id


__all__ = [
    "QaSubjectProjectError",
    "SCOPED_RUN_FUNCTIONS",
    "bound_target_project_for_member",
    "resolve_run_qa_subject",
]

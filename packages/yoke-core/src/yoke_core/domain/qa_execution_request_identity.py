"""Resolve continuation authority from the execution, never a release selector."""

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.qa_request_subjects import EXECUTION_SUBJECT_FUNCTIONS


EXECUTION_FUNCTIONS = EXECUTION_SUBJECT_FUNCTIONS | {
    "test_machine.plan_case.begin",
    "test_machine.plan_case.submit",
    "test_machine.mission.ready",
    "test_machine.mission.access",
}


def is_execution_request(request):
    return request.function in EXECUTION_FUNCTIONS


def resolve_execution_request(conn, request, execution=None):
    """Validate optional scope hints and return a server-derived subject.

    Permission and claim readers use an unlocked row. Mutating handlers call
    this again with their locked row so a concurrent takeover cannot leave a
    stale release selector between authorization and the write.
    """
    from yoke_core.domain.qa_deployment_function_subject import (
        QaSubjectProjectError,
        _checkin_project,
    )
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution
    from yoke_core.domain.qa_plan_execution_stop import execution_project_id
    from yoke_core.domain.function_target_row_project import slug_for_project_id
    from yoke_core.domain.project_identity import resolve_project_id

    supplied = request.target
    if supplied.kind not in {"item", "global"} or supplied.deployment_run_id:
        raise QaSubjectProjectError(
            "qa_execution_release_selector_removed: continuation resolves ownership "
            "from execution_id; omit the deployment release and use the execution's "
            "item or project only when supplying an authorization scope"
        )
    if execution is None:
        execution_id = str((request.payload or {}).get("execution_id") or "")
        if not execution_id:
            raise QaSubjectProjectError(
                "qa_execution_id_required: supply execution_id to resolve continuation authority"
            )
        execution = select_plan_execution(conn, execution_id, lock=False)
    run_id = execution.get("deployment_run_id")
    member = execution.get("deployment_member_item_id")
    if (
        run_id
        and request.function == "qa.plan_execution.abort"
        and not execution.get("execution_target")
    ):
        from yoke_core.domain.qa_deployment_function_subject import (
            resolve_run_qa_subject,
        )

        # Abandoning a cursor does not dispatch cases or require a target snapshot.
        stopped = request.model_copy(
            update={
                "target": TargetRef(
                    kind="deployment_run", deployment_run_id=str(run_id)
                )
            }
        )
        project_id, slug, _ = resolve_run_qa_subject(conn, stopped)
    elif run_id:
        project_id, slug = _checkin_project(conn, execution["id"], member)
    else:
        project_id = execution_project_id(conn, execution)
        slug = slug_for_project_id(conn, project_id)
    if supplied.kind == "item":
        item_id = supplied.item_id
        allowed = {execution.get("item_id"), member} - {None}
        shared = (
            (execution.get("execution_target") or {}).get("deployment") or {}
        ).get("shared_plan")
        if shared and run_id:
            from yoke_core.domain.deployment_qa_plan_groups import attaching_members

            allowed.update(attaching_members(conn, str(run_id), int(shared["plan_id"])))
        if item_id is None or int(item_id) not in allowed:
            raise QaSubjectProjectError(
                "qa_execution_item_mismatch: this item does not own or attach to "
                "the execution; use its actual member or project"
            )
    for hint in (supplied.project_id, (request.payload or {}).get("project")):
        if not hint:
            continue
        try:
            hinted_id = resolve_project_id(conn, str(hint))
        except LookupError as exc:
            raise QaSubjectProjectError(
                f"qa_execution_project_unknown: use the execution's project {slug!r}"
            ) from exc
        if hinted_id != project_id:
            raise QaSubjectProjectError(
                f"qa_execution_project_mismatch: use the execution's project {slug!r}"
            )
    if run_id:
        target = TargetRef(
            kind="deployment_run", deployment_run_id=str(run_id), project_id=slug
        )
    elif execution.get("item_id") is not None:
        target = TargetRef(kind="item", item_id=int(execution["item_id"]))
    else:
        target = TargetRef(kind="global", project_id=slug)
    return request.model_copy(update={"target": target})

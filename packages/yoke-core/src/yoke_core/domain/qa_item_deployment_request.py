"""Resolve fresh item QA through its existing delivery completion authority."""

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_item_stage_run_selection import select_stage_run
from yoke_core.domain.qa_plan_management import QaPlanError

#: Payload key naming the run the item's holder chose; it becomes the target.
REQUESTED_RUN = "deployment_run_id"


def execution_member_id(conn, member):
    if member is None:
        return None
    from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none

    item_id = resolve_item_ref_or_none(conn, member)
    if item_id is None:
        raise QaPlanError(
            "qa_member_unknown: no work item resolves from the supplied member selector"
        )
    return item_id


def resolve_item_deployment_request(conn, request):
    """Retarget ``--item --stage S`` to the one live run that answers it.

    The selection is :func:`select_stage_run`'s. A holder-named run travels as
    ``deployment_run_id`` in the payload and is validated, never trusted.
    """
    payload = dict(request.payload or {})
    requested = payload.pop(REQUESTED_RUN, None)
    if request.target.kind != "item" or not payload.get("deployment_stage"):
        if requested:
            raise QaPlanError(
                "qa_item_run_scope_invalid: --deployment-run-id with --item needs "
                "--stage STAGE; a workflow transition has no deployment run"
            )
        return request
    item_id = request.target.item_id
    if (
        item_id is None
        or payload.get("transition_id")
        or payload.get("deployment_member")
    ):
        raise QaPlanError(
            "qa_item_stage_scope_invalid: use the item and its QA stage without a "
            "workflow transition or a separate member selector"
        )
    plan = None
    if payload.get("plan"):
        from yoke_core.domain.qa_plan_retire import resolve_plan

        project = conn.execute(
            "SELECT p.slug FROM projects p JOIN items i ON i.project_id=p.id WHERE i.id=%s",
            (int(item_id),),
        ).fetchone()[0]
        plan = resolve_plan(conn, project=project, plan=payload["plan"])
    run_id = select_stage_run(
        conn,
        item_id=int(item_id),
        stage=payload["deployment_stage"],
        item_ref=render_item_ref(conn, int(item_id)),
        plan=plan,
        requested_run_id=requested,
    )
    member_scoped = True
    if plan is not None:
        from yoke_core.domain.deployment_qa_plan_ownership import plan_owners

        owners = plan_owners(conn, run_id)
        selected = int(plan["id"])
        # Only an admitted shared plan selects the driver's memberless group.
        # A new correction plan retains the member whose failed case it replaces.
        member_scoped = selected not in owners or owners[selected] is not None
    return request.model_copy(
        update={
            "target": TargetRef(
                kind="deployment_run",
                deployment_run_id=run_id,
                project_id=request.target.project_id,
            ),
            "payload": {
                **payload,
                **(
                    {"deployment_member": render_item_ref(conn, int(item_id))}
                    if member_scoped
                    else {}
                ),
            },
        }
    )

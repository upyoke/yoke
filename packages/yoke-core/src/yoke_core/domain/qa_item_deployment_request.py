"""Resolve fresh item QA through its existing delivery completion authority."""

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.deployment_item_completion_runs import latest_qa_member_run
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_management import QaPlanError


def execution_member_id(conn, member):
    if member is None:
        return None
    from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none

    item_id = resolve_item_ref_or_none(conn, member)
    if item_id is None:
        raise QaPlanError(f"deployment member {member!r} not found")
    return item_id


def resolve_item_deployment_request(conn, request):
    payload = request.payload or {}
    if request.target.kind != "item" or not payload.get("deployment_stage"):
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
    target_env = ""
    if payload.get("plan"):
        from yoke_core.domain.qa_plan_retire import resolve_plan

        project = conn.execute(
            "SELECT p.slug FROM projects p JOIN items i ON i.project_id=p.id WHERE i.id=%s",
            (int(item_id),),
        ).fetchone()[0]
        plan = resolve_plan(conn, project=project, plan=payload["plan"])
        if plan.get("target_environment_id"):
            target_env = conn.execute(
                "SELECT name FROM environments WHERE id=%s",
                (plan["target_environment_id"],),
            ).fetchone()[0]
    run = latest_qa_member_run(conn, item_id=int(item_id), target_env=target_env)
    if run is None:
        raise QaPlanError(
            "qa_item_delivery_unavailable: this item has no current QA-capable "
            "completion membership; inspect its delivery before starting QA"
        )
    return request.model_copy(
        update={
            "target": TargetRef(
                kind="deployment_run",
                deployment_run_id=str(run["id"]),
                project_id=request.target.project_id,
            ),
            "payload": {
                **payload,
                "deployment_member": render_item_ref(conn, int(item_id)),
            },
        }
    )

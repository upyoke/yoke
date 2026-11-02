"""Resolve fresh item QA through its existing delivery completion authority."""

import shlex
from uuid import uuid4

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.deployment_item_completion_runs import (
    completion_runs,
    latest_qa_member_run,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_management import QaPlanError


class QaItemStageUnavailable(QaPlanError):
    code = "qa_item_stage_unavailable"


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
    if payload.get("plan"):
        run = latest_qa_member_run(conn, item_id=int(item_id), target_env=target_env)
    else:
        run = next(
            (
                candidate
                for candidate in completion_runs(conn, int(item_id), include_qa=True)
                if candidate["status"] == "executing"
                and candidate["current_stage"] == payload["deployment_stage"]
            ),
            None,
        )
        if run is None:
            raise QaItemStageUnavailable(
                _stage_run_recovery(conn, int(item_id), payload["deployment_stage"])
            )
    if run is None:
        raise QaPlanError(
            "qa_item_delivery_unavailable: this item has no current QA-capable "
            "completion membership; inspect its delivery before starting QA"
        )
    member_scoped = True
    if payload.get("plan"):
        from yoke_core.domain.deployment_qa_plan_ownership import plan_owners

        owners = plan_owners(conn, str(run["id"]))
        selected = int(plan["id"])
        # Only an admitted shared plan selects the driver's memberless group.
        # A new correction plan retains the member whose failed case it replaces.
        member_scoped = selected not in owners or owners[selected] is not None
    return request.model_copy(
        update={
            "target": TargetRef(
                kind="deployment_run",
                deployment_run_id=str(run["id"]),
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


def _stage_run_recovery(conn, item_id, stage):
    from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow

    project = conn.execute(
        "SELECT p.slug FROM projects p JOIN items i ON i.project_id=p.id WHERE i.id=%s",
        (item_id,),
    ).fetchone()[0]
    stage_flow = conn.execute(
        "SELECT f.id FROM deployment_flows f "
        "JOIN environments e ON e.id=f.target_environment_id "
        "JOIN items i ON i.project_id=f.project_id "
        "WHERE i.id=%s AND e.name='stage' AND f.status='active' ORDER BY f.id",
        (item_id,),
    ).fetchone()
    flow = stage_flow[0] if stage_flow else item_completion_flow(conn, item_id)
    command = shlex.join(
        [
            "yoke",
            "deployment-runs",
            "create",
            project,
            flow or "FLOW",
            "--environment",
            "stage",
            "--idempotency-key",
            str(uuid4()),
        ]
    )
    return (
        f"qa_item_stage_unavailable: no member run is executing stage {stage!r} "
        f"for {render_item_ref(conn, item_id)}. Ask steering or the release driver "
        f"to start a Stage run that enrolls this item: `{command}`. "
        "The driver must select a Stage-capable flow and confirm enrollment, then "
        f"drive the run to {stage!r} before you retry QA. "
        "This recovery does not authorize the item holder to create a run."
    )

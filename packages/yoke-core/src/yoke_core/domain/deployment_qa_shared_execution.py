"""Route a deployment QA begin to its subject: a member's cases or a plan group.

A member walks only its own item cases. ``--plan P`` at an item-scoped stage
walks P's open plan group, which runs once for the whole release; naming an
attaching ``--item`` only records who asked. A requirement id resolves the
subject that owns it.
"""

from functools import wraps


def _requirement_begin(conn, begin, kwargs):
    from yoke_core.domain.deployment_qa_shared_plans import requirement_subject
    from yoke_core.domain.deployment_runs_lock import (
        RUN_READ_ATTEMPTS,
        DeploymentRunChanging,
    )
    from yoke_core.domain.qa_plan_execution_begin_admission import (
        BeginInputsChanged,
        begin_inputs,
    )

    for _attempt in range(RUN_READ_ATTEMPTS):
        inputs = begin_inputs(
            conn, kwargs["deployment_run_id"], kwargs["deployment_stage"]
        )
        subject = requirement_subject(conn, kwargs["requirement_id"])
        try:
            return begin(
                conn,
                **{**kwargs, "_deployment_subject": subject, "_run_inputs": inputs},
            )
        except BeginInputsChanged:
            conn.rollback()
    raise DeploymentRunChanging(str(kwargs["deployment_run_id"]))


def _group_begin(conn, begin, kwargs):
    """Begin the named plan's open group; None when the stage runs run QA."""
    from yoke_core.domain.deployment_qa_plan_group_writes import resolve_group_subject
    from yoke_core.domain.deployment_qa_plan_groups import attaching_members
    from yoke_core.domain.project_identity import render_item_ref

    run_id, stage = str(kwargs["deployment_run_id"]), str(kwargs["deployment_stage"])
    group = resolve_group_subject(
        conn, run_id, stage, str(kwargs["plan"]), require_active=True
    )
    if group is None:
        return None
    member = kwargs.get("deployment_member_item_id")
    plan_id = int(group["shared_plan"]["plan_id"])
    if member is not None and int(member) not in attaching_members(
        conn, run_id, plan_id
    ):
        raise ValueError(
            f"plan_group_member_unattached: {render_item_ref(conn, int(member))} does "
            f"not attach plan {kwargs['plan']!r}, so its group does not answer it. "
            f"Run the group without --item: `yoke qa plan run --deployment-run-id "
            f"{run_id} --stage {stage} --plan {kwargs['plan']}`"
        )
    return begin(
        conn,
        **{
            **kwargs,
            "deployment_member_item_id": None,
            "_requesting_member_item_id": member,
            "_deployment_subject": group,
        },
    )


def route_shared_plan_execution(begin):
    """Send a begin to the subject it names: requirement, plan group or member."""

    @wraps(begin)
    def routed(conn, **kwargs):
        if kwargs.get("_deployment_subject") is not None or not kwargs.get(
            "deployment_stage"
        ):
            return begin(conn, **kwargs)
        if kwargs.get("requirement_id") is not None:
            return _requirement_begin(conn, begin, kwargs)
        if kwargs.get("plan") is not None:
            started = _group_begin(conn, begin, kwargs)
            if started is not None:
                return started
        return begin(conn, **kwargs)

    return routed

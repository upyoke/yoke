"""Route a member's ordered walk through its shared plan subjects.

Routing reads every member of the run, so it runs before the run row lock,
inside one presentation scope where each per-member fact is one set read.
The begin it routes to takes the lock only to re-check and write.
"""

from dataclasses import dataclass, field
from functools import wraps
from typing import Any

from yoke_core.domain.deployment_qa_presentation_facts import run_presentation
from yoke_core.domain.deployment_qa_presentation_reads import presentation_operation
from yoke_core.domain.qa_obligation_settlement import (
    settled_obligation_sql,
    unanswered_attempt_sql,
)


@dataclass
class _Route:
    """Where a member's begin goes, decided from reads before the run lock."""

    inputs: str
    plan_filter: str = ""
    plan_params: tuple = ()
    pending: list = field(default_factory=list)
    pending_digests: list = field(default_factory=list)
    completed: Any = None
    private_first: bool = False
    no_groups: bool = False


@presentation_operation
@run_presentation
def _read_route(conn, *, run_id, stage, member, selected, session_id):
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_materialization_projection import (
        MaterializationProjection,
    )
    from yoke_core.domain.deployment_qa_shared_plans import member_plan_subjects
    from yoke_core.domain.deployment_qa_stage_acceptance import (
        completed_execution,
        stage_acceptance,
    )
    from yoke_core.domain.deployment_qa_stage_case_failures import case_failures
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.qa_execution_environment_target import target_digest
    from yoke_core.domain.qa_plan_execution_begin_admission import begin_inputs

    projection = MaterializationProjection(conn, run_id)
    route = _Route(
        begin_inputs(conn, run_id, stage, run_fingerprint=projection.fingerprint)
    )
    subject = deployment_qa_stage_subject(
        conn, run_id=run_id, stage_name=stage, member_item_id=member
    )
    target = deployment_qa_execution_target(conn, subject)
    groups = member_plan_subjects(conn, subject, target, projection=projection)
    digests = [
        target_digest(deployment_qa_execution_target(conn, group)) for group in groups
    ]
    if selected is not None:
        route.plan_filter = (
            " AND plan_id IN (SELECT id FROM qa_plans "
            "WHERE slug=%s OR CAST(id AS TEXT)=%s)"
        )
        route.plan_params = (str(selected), str(selected))
        selected_targets = {
            str(row[0])
            for row in conn.execute(
                "SELECT DISTINCT execution_target_digest FROM qa_requirements "
                "WHERE deployment_run_id=%s AND deployment_stage=%s "
                "AND deployment_member_item_id IS NULL" + route.plan_filter,
                (run_id, stage, *route.plan_params),
            ).fetchall()
        }
        kept = [i for i, digest in enumerate(digests) if digest in selected_targets]
        groups, digests = [groups[i] for i in kept], [digests[i] for i in kept]
    if not groups:
        route.no_groups = True
        return route
    from yoke_core.domain.qa_plan_execution_store import (
        live_plan_execution_id,
        select_plan_execution,
    )

    # The caller's own live walk resumes first, whatever its group's state.
    own_id = live_plan_execution_id(
        conn, deployment_run_id=run_id, deployment_stage=stage, session_id=session_id
    )
    own = (
        select_plan_execution(conn, own_id, lock=False)["execution_target_digest"]
        if own_id
        else None
    )
    order = sorted(range(len(groups)), key=lambda i: digests[i] != own)
    groups, digests = [groups[i] for i in order], [digests[i] for i in order]
    for group, digest in zip(groups, digests):
        if selected is not None or digest == own:
            route.pending.append(group)
            route.pending_digests.append(digest)
            continue
        acceptance = stage_acceptance(
            conn,
            subject=group,
            target=deployment_qa_execution_target(conn, group),
            acceptance_qa_kind="deployment_stage_acceptance",
        )
        recorded = completed_execution(
            conn,
            run_id=run_id,
            stage_name=stage,
            member_item_id=None,
            execution_target_digest=digest,
        )
        if recorded is not None and not case_failures(
            conn,
            run_id=run_id,
            stage_name=stage,
            member_item_id=None,
            execution_target_digest=digest,
            shared_plan_id=group["shared_plan"]["plan_id"],
        ):
            route.completed = recorded
        elif not acceptance.accepted:
            route.pending.append(group)
            route.pending_digests.append(digest)
    private = conn.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND deployment_member_item_id=%s AND method_id IS NOT NULL "
        f"AND NOT {settled_obligation_sql(conn)} AND {unanswered_attempt_sql(conn)}"
        + route.plan_filter,
        (run_id, stage, member, *route.plan_params),
    ).fetchone()[0]
    if private and not (
        stage_acceptance(
            conn,
            subject={**subject, "shared_plans_resolved": True},
            target=target,
            acceptance_qa_kind="deployment_stage_acceptance",
        ).accepted
    ):
        # Private evidence has its own cursor and custody. Completing it
        # must not start a shared campaign as a client-side continuation.
        route.private_first = True
        return route
    return route


def _begin_routed(conn, begin, kwargs):
    """Route unlocked, then begin; the begin re-checks the route's inputs."""
    member = kwargs["deployment_member_item_id"]
    run_id, stage = kwargs.get("deployment_run_id"), kwargs["deployment_stage"]
    route = _read_route(
        conn,
        run_id=run_id,
        stage=stage,
        member=member,
        selected=kwargs.get("plan"),
        session_id=kwargs.get("session_id"),
    )
    inputs = route.inputs
    if route.no_groups or route.private_first:
        return begin(conn, **{**kwargs, "_run_inputs": inputs})
    from yoke_core.domain.qa_plan_nothing_owed import QaPlanNothingOwed
    from yoke_core.domain.qa_stage_execution_holders import StageRosterHeld

    held = None
    owed_nothing = None
    for index, group in enumerate(route.pending):
        try:
            result = begin(
                conn,
                **{
                    **kwargs,
                    "deployment_member_item_id": None,
                    "_requesting_member_item_id": member,
                    "_deployment_subject": group,
                    "_run_inputs": inputs,
                },
            )
        except StageRosterHeld as exc:
            # Another session walks every owed case of this group; try the next.
            held = held or (exc.execution, route.pending_digests[index])
            continue
        except QaPlanNothingOwed as exc:
            # Its blocker is not a case to run; another group may still owe one.
            owed_nothing = owed_nothing or exc
            continue
        own_remaining = result.get("remaining_requirement_count") or 0
        return {
            **result,
            "remaining_requirement_count": own_remaining
            + sum(
                conn.execute(
                    "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
                    "AND deployment_member_item_id IS NULL AND execution_target_digest=%s AND method_id IS NOT NULL "
                    f"AND waived_at IS NULL AND {unanswered_attempt_sql(conn)}"
                    + route.plan_filter,
                    (run_id, stage, digest, *route.plan_params),
                ).fetchone()[0]
                for other, digest in enumerate(route.pending_digests)
                if other != index
            ),
        }
    if held is not None:
        from yoke_core.domain.deployment_qa_shared_wait import shared_execution_wait

        return shared_execution_wait(
            held[0], member=member, desired_target_digest=held[1]
        )
    if owed_nothing is not None:
        raise owed_nothing
    if route.completed is not None:
        return {**route.completed, "remaining_requirement_count": 0}
    from yoke_core.domain.qa_plan_empty_roster import QaPlanRosterDischarged

    raise QaPlanRosterDischarged(
        "All attached shared plan cases were discharged; no execution remains.",
        requirement_id=0,
        qa_kind="shared_plan_discharge",
    )


def route_shared_plan_execution(begin):
    """Reuse completed group evidence and execute only this member's owed groups."""

    @wraps(begin)
    def routed(conn, **kwargs):
        member = kwargs.get("deployment_member_item_id")
        if member is None or kwargs.get("_deployment_subject") is not None:
            return begin(conn, **kwargs)
        from yoke_core.domain.deployment_runs_lock import (
            RUN_READ_ATTEMPTS,
            DeploymentRunChanging,
        )
        from yoke_core.domain.qa_plan_execution_authority import (
            require_member_attached,
        )
        from yoke_core.domain.qa_plan_execution_begin_admission import (
            BeginInputsChanged,
        )

        run_id, stage = kwargs.get("deployment_run_id"), kwargs.get("deployment_stage")
        if not stage:
            return begin(conn, **kwargs)
        from yoke_core.domain.workflow_item_binding_lock import (
            lock_item_workflow_bindings,
        )

        # Every write commits, so each rollback releases only a read-only answer.
        try:
            for _attempt in range(RUN_READ_ATTEMPTS):
                # The member's own row lock serializes with its removal; the
                # run stays free while the route is read.
                lock_item_workflow_bindings(conn, (int(member),))
                require_member_attached(conn, run_id, member)
                try:
                    return _begin_routed(conn, begin, kwargs)
                except BeginInputsChanged:
                    # A change landed between the read and the lock: release
                    # the lock and read again unlocked.
                    conn.rollback()
            raise DeploymentRunChanging(str(run_id))
        finally:
            conn.rollback()

    return routed

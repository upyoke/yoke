"""Materialize and begin a manual project plan in existing QA records."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from yoke_core.domain.db_helpers import instant_parameter, utc_now, query_one
from yoke_core.domain.qa_plan_management import _project_id
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
    marker,
    select_plan_execution,
    roster_digest,
    same_owner,
    resume_owned_plan_execution,
)
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_partition_chains import partition_key
from yoke_core.domain.qa_plan_partition_custody import (
    PartitionScope,
    admit_partition,
    live_partition_executions,
    partition_unavailable,
)


def require_standalone_project(conn: Any, execution: dict, project: str) -> None:
    plan = query_one(
        conn,
        f"SELECT project_id FROM qa_plans WHERE id={marker(conn)}",
        (execution.get("standalone_plan_id"),),
    )
    if plan is None or int(plan["project_id"]) != _project_id(conn, project):
        raise QaPlanExecutionStateError(
            "standalone_project_mismatch: execution belongs to another project; name its project"
        )


def begin_requested_standalone_execution(conn, request, parsed):
    if not parsed.plan or any(
        (parsed.transition_id, parsed.deployment_stage, parsed.deployment_member)
    ):
        raise QaPlanExecutionStateError(
            "standalone_subject_invalid: name only plan and project"
        )
    return begin_standalone_execution(
        conn,
        plan=parsed.plan,
        project=str(request.target.project_id),
        actor_id=request.actor.actor_id,
        session_id=request.actor.session_id,
        test_machine=parsed.test_machine,
        continue_mission=parsed.continue_mission,
        source_revision=parsed.source_revision,
        source_ref=parsed.source_ref,
        checkout_path=parsed.checkout_path,
        partition=parsed.partition,
    )


def _plan(conn: Any, plan: str, project: str) -> dict:
    p = marker(conn)
    row = query_one(
        conn,
        "SELECT * FROM qa_plans "
        f"WHERE project_id={p} AND (slug={p} OR CAST(id AS TEXT)={p}) "
        "AND retired_at IS NULL" + (" FOR UPDATE" if p == "%s" else ""),
        (_project_id(conn, project), plan, plan),
    )
    if row is None:
        raise QaPlanExecutionStateError(
            f"standalone_plan_not_found: {plan!r} in {project!r}; select a live project plan"
        )
    return dict(row)


def _roster(
    conn: Any,
    plan: dict,
    execution_id: str,
    *,
    session_id: str,
    source_revision: str | None,
    source_ref: str | None,
    checkout_path: str | None,
    selected_cases: set[tuple[str, int]] | None,
) -> list[dict]:
    from yoke_core.domain.qa_plan_case_definition import case_baselines, plan_cases
    from yoke_core.domain.qa_plan_requirement_snapshot import insert_requirement
    from yoke_core.domain.qa_execution_environment_target import (
        resolve_plan_execution_target,
    )
    from yoke_core.domain.qa_case_execution_context import (
        get_case_execution_context,
        execution_host_capability_kinds,
    )

    cases = plan_cases(conn, int(plan["id"]))
    if not cases:
        raise QaPlanExecutionStateError(
            "standalone_empty_plan: add cases before running this plan"
        )
    target = resolve_plan_execution_target(conn, plan_id=int(plan["id"]))
    from yoke_core.domain.qa_plan_case_targets import require_single_execution_target

    require_single_execution_target(cases, target)
    capabilities = execution_host_capability_kinds(conn, session_id=session_id)
    roster = []
    for case in cases:
        for position, baseline in enumerate(case_baselines(case), 1):
            if selected_cases is not None and (case["case_key"], position) not in selected_cases:
                continue
            requirement_id = insert_requirement(
                conn,
                standalone_execution_id=execution_id,
                plan=plan,
                attachment={"qa_phase": "manual_acceptance"},
                case=case,
                baseline=baseline,
                baseline_position=position,
                now=utc_now(),
                execution_target=target,
            )
            if requirement_id is None:
                raise QaPlanExecutionStateError(
                    "standalone_snapshot_conflict: retry this plan run"
                )
            context = get_case_execution_context(
                conn,
                requirement_id=requirement_id,
                host_capability_kinds=capabilities,
            )
            runner = context["runner_id"]
            if source_revision:
                context["standalone_source_revision"] = source_revision.lower()
            if runner not in {
                "worktree_run",
                "ci_run",
                "host_control",
                "browser_substrate",
                "agent_mission",
            }:
                raise QaPlanExecutionStateError(
                    f"standalone_runner_unsupported: {runner!r}; select a registered standalone runner"
                )
            if runner in {"worktree_run", "ci_run"}:
                if (
                    not source_revision
                    or len(source_revision) != 40
                    or any(c not in "0123456789abcdef" for c in source_revision.lower())
                ):
                    raise QaPlanExecutionStateError(
                        "standalone_commit_required: command cases require --expected-sha with a full commit SHA"
                    )
                if runner == "worktree_run" and not checkout_path:
                    raise QaPlanExecutionStateError(
                        "standalone_checkout_required: command cases require --checkout-path at --expected-sha"
                    )
                if runner == "ci_run" and not source_ref:
                    raise QaPlanExecutionStateError(
                        "standalone_ci_ref_required: name --expected-branch whose remote tip is --expected-sha"
                    )
                if runner == "ci_run" and not context["method_config"].get(
                    "ci_workflow"
                ):
                    raise QaPlanExecutionStateError(
                        "standalone_ci_workflow_required: declare method_config.ci_workflow on the case"
                    )
                context.update(
                    standalone_source_ref=source_ref,
                    standalone_checkout_path=checkout_path,
                )
            roster.append(
                {
                    **context,
                    "ordinal": len(roster),
                    "case_position": int(case["position"]),
                    "baseline_position": position,
                }
            )
    roster.sort(key=lambda row: (row["baseline_position"], row["case_position"]))
    return [{**row, "ordinal": ordinal} for ordinal, row in enumerate(roster)]


def begin_standalone_execution(
    conn: Any,
    *,
    plan: str,
    project: str,
    actor_id: str | None,
    session_id: str,
    test_machine: str | None = None,
    continue_mission: bool = False,
    continuation_execution_id: str | None = None,
    source_revision: str | None = None,
    source_ref: str | None = None,
    checkout_path: str | None = None,
    partition: str | None = None,
) -> dict:
    """Fresh snapshots per manual run; a live run resumes its immutable roster."""
    from yoke_core.domain.qa_plan_execution_continuation import (
        require_continuable_execution,
    )
    from yoke_core.domain.qa_plan_execution_roster import validate_roster_machine
    from yoke_core.domain.qa_plan_execution_target_snapshot import (
        execution_target_for_roster,
    )
    from yoke_core.domain.qa_standalone_context import (
        require_same_source,
        require_same_mission_roster,
    )

    if not session_id:
        raise QaPlanExecutionStateError(
            "standalone_session_required: run in a registered session"
        )
    selected = _plan(conn, plan, project)
    plan_id = int(selected["id"])
    scope = PartitionScope(standalone_plan_id=plan_id)
    own = next((
        row for row in live_partition_executions(conn, scope) if row["session_id"] == session_id
    ), None)
    prior = select_plan_execution(conn, own["id"], lock=True) if own else None
    if prior and prior["state"] in LIVE_PLAN_EXECUTION_STATES:
        if continue_mission:
            raise QaPlanExecutionStateError(
                "standalone_live_execution: omit --continue-mission to resume it"
            )
        if not same_owner(prior, actor_id=actor_id, session_id=session_id) or (
            partition and partition_key(prior["roster"], standalone=True) != partition
        ):
            raise partition_unavailable(
                partition or "<selected>",
                f"conflicts with this session's execution {prior['id']}; resume it by execution id",
            )
        from yoke_core.domain.qa_environment_served_build import observe_resume

        observe_resume(conn, prior)
        require_same_source(
            prior["roster"],
            source_revision=source_revision,
            source_ref=source_ref,
            checkout_path=checkout_path,
        )
        validate_roster_machine(conn, prior["roster"], test_machine)
        return resume_owned_plan_execution(conn, prior, digest=str(prior["roster_digest"]))
    continuation = None
    if continue_mission:
        continuation = require_continuable_execution(
            conn,
            standalone_plan_id=plan_id,
            expected_execution_id=continuation_execution_id,
        )
    from yoke_core.domain.qa_plan_partitions import select_partition
    from yoke_core.domain.qa_standalone_partitions import standalone_partition_views

    selected_cases = None
    if continuation is not None:
        cases = continuation["roster"]
        selected_key = partition_key(cases, standalone=True)
    else:
        views = standalone_partition_views(conn, plan_id, source_revision=source_revision)
        if partition is None and all(not view.partition.predecessors for view in views):
            cases = [case for view in views for case in view.partition.roster]
            selected_key = "<selected>"
        else:
            view = select_partition(views, key=partition, session_id=session_id, allow_failed=True)
            if view is None:
                raise partition_unavailable(
                    partition or "<selected>", "has no owed cases at this revision"
                )
            cases, selected_key = view.partition.roster, view.partition.key
            selected_cases = {(row["case_key"], row["baseline_position"]) for row in cases}
    if continuation is not None:
        selected_cases = {(row["case_key"], row["baseline_position"]) for row in cases}
    admit_partition(conn, scope, key=selected_key, roster=cases, session_id=session_id)
    execution_id = str(uuid4())
    roster = _roster(
        conn,
        selected,
        execution_id,
        session_id=session_id,
        source_revision=source_revision,
        source_ref=source_ref,
        checkout_path=checkout_path,
        selected_cases=selected_cases,
    )
    validate_roster_machine(conn, roster, test_machine)
    if continuation:
        require_same_mission_roster(continuation, roster)
    target, digest = execution_target_for_roster(roster)
    from yoke_core.domain.qa_environment_served_build import observe_build

    build = observe_build(conn, target)
    now = utc_now()
    values = {
        **build,
        "id": execution_id,
        "standalone_plan_id": plan_id,
        "actor_id": actor_id,
        "session_id": session_id,
        "roster_digest": roster_digest(roster),
        "roster_json": canonical(roster),
        "execution_target_json": canonical(target),
        "execution_target_digest": digest,
        "continues_execution_id": str(continuation["id"]) if continuation else None,
        "cursor_ordinal": 0,
        "state": "active",
        "created_at": instant_parameter(conn, now),
        "heartbeat_at": instant_parameter(conn, now),
    }
    conn.execute(
        f"INSERT INTO qa_plan_executions({','.join(values)}) "
        f"VALUES ({','.join([marker(conn)] * len(values))})",
        tuple(values.values()),
    )
    conn.commit()
    return select_plan_execution(conn, execution_id, lock=False)

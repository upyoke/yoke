"""Materialize and begin a manual project plan in existing QA records."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from yoke_core.domain.db_helpers import iso8601_now, query_one
from yoke_core.domain.qa_plan_management import _project_id
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
    marker,
    select_plan_execution,
    roster_digest,
    same_owner,
    resume_owned_plan_execution,
    STANDALONE_HISTORY_ORDER_SQL,
)
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_STATES,
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
        machine=parsed.machine,
        continue_mission=parsed.continue_mission,
        source_revision=parsed.source_revision,
        source_ref=parsed.source_ref,
        checkout_path=parsed.checkout_path,
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


def _latest(conn: Any, plan_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id FROM qa_plan_executions "
        f"WHERE standalone_plan_id={marker(conn)} "
        f"ORDER BY {STANDALONE_HISTORY_ORDER_SQL} LIMIT 1",
        (plan_id,),
    ).fetchone()
    return select_plan_execution(conn, str(row[0]), lock=True) if row else None


def _roster(
    conn: Any,
    plan: dict,
    execution_id: str,
    *,
    session_id: str,
    source_revision: str | None,
    source_ref: str | None,
    checkout_path: str | None,
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
    capabilities = execution_host_capability_kinds(conn, session_id=session_id)
    roster = []
    for case in cases:
        for position, baseline in enumerate(case_baselines(case), 1):
            requirement_id = insert_requirement(
                conn,
                standalone_execution_id=execution_id,
                plan=plan,
                attachment={"qa_phase": "manual_acceptance"},
                case=case,
                baseline=baseline,
                baseline_position=position,
                now=iso8601_now(),
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
                    standalone_source_revision=source_revision.lower(),
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
    return roster


def begin_standalone_execution(
    conn: Any,
    *,
    plan: str,
    project: str,
    actor_id: str | None,
    session_id: str,
    machine: str | None = None,
    continue_mission: bool = False,
    source_revision: str | None = None,
    source_ref: str | None = None,
    checkout_path: str | None = None,
) -> dict:
    """Fresh snapshots per manual run; a live run resumes its immutable roster."""
    from yoke_core.domain.qa_plan_execution_authority import plan_execution_is_abandoned
    from yoke_core.domain.qa_plan_execution_lifecycle import (
        finish_plan_execution,
        STALE_PLAN_EXECUTION_REASON,
    )
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
    prior = _latest(conn, plan_id)
    if prior and prior["state"] in LIVE_PLAN_EXECUTION_STATES:
        if continue_mission:
            raise QaPlanExecutionStateError(
                "standalone_live_execution: omit --continue-mission to resume it"
            )
        if same_owner(prior, actor_id=actor_id, session_id=session_id):
            require_same_source(
                prior["roster"],
                source_revision=source_revision,
                source_ref=source_ref,
                checkout_path=checkout_path,
            )
            validate_roster_machine(conn, prior["roster"], machine)
            return resume_owned_plan_execution(
                conn, prior, digest=str(prior["roster_digest"])
            )
        if not plan_execution_is_abandoned(conn, prior):
            raise QaPlanExecutionStateError(
                "standalone_execution_owned: another session owns the live run; wait or have its owner abort it"
            )
        finish_plan_execution(
            conn, prior, state="aborted", reason=STALE_PLAN_EXECUTION_REASON
        )
        selected = _plan(conn, plan, project)
    continuation = None
    if continue_mission:
        continuation = require_continuable_execution(conn, standalone_plan_id=plan_id)
    execution_id = str(uuid4())
    roster = _roster(
        conn,
        selected,
        execution_id,
        session_id=session_id,
        source_revision=source_revision,
        source_ref=source_ref,
        checkout_path=checkout_path,
    )
    validate_roster_machine(conn, roster, machine)
    if continuation:
        require_same_mission_roster(continuation, roster)
    target, digest = execution_target_for_roster(roster)
    now = iso8601_now()
    values = {
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
        "created_at": now,
        "heartbeat_at": now,
    }
    conn.execute(
        f"INSERT INTO qa_plan_executions({','.join(values)}) "
        f"VALUES ({','.join([marker(conn)] * len(values))})",
        tuple(values.values()),
    )
    conn.commit()
    return select_plan_execution(conn, execution_id, lock=False)

"""Materialize frozen deployment QA cases onto scoped requirements."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.qa_deployment_member_attached_plans import (
    attached_member_plans,
)
from yoke_core.domain.qa_deployment_case_content_refresh import (
    refreshed_case_keys,
)
from yoke_core.domain.db_helpers import iso8601_now, query_rows
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_admission_materialization import (
    materialize_admitted_requirement,
    member_requirements,
)
from yoke_core.domain.deployment_qa_direct_case_target import (
    bind_existing_direct_deployment_cases,
)
from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    require_existing_target,
    require_requirement_id_target,
)


def _flow_plan(subject: Mapping[str, Any]) -> list[dict[str, Any]]:
    stage = str(subject["stage"]["name"])
    return [
        dict(selection)
        for selection in subject["flow_snapshot"].get("selections") or []
        if isinstance(selection, Mapping) and str(selection.get("stage") or "") == stage
    ]


def _member_plans(
    subject: Mapping[str, Any], *, target: Mapping[str, Any]
) -> list[dict[str, Any]]:
    snapshot = subject.get("member_snapshot")
    if not isinstance(snapshot, Mapping):
        return []
    environment = target.get("environment")
    environment_id = (
        environment.get("id") if isinstance(environment, Mapping) else None
    )
    selected: list[dict[str, Any]] = []
    for value in snapshot.get("plans") or []:
        if not isinstance(value, Mapping):
            continue
        attachment = value.get("attachment")
        plan = value.get("plan")
        if not isinstance(attachment, Mapping) or not isinstance(plan, Mapping):
            continue
        if str(attachment.get("qa_phase") or "") != "post_deploy":
            continue
        plan_environment = plan.get("target_environment_id")
        if plan_environment is not None and int(plan_environment) != int(
            environment_id or 0
        ):
            continue
        selected.append(dict(value))
    return selected


class QaCasesNotSelectedError(QaPlanError):
    """No cases are selected for this stage subject yet.

    Deliberately its own type, because it is the ONLY materialization
    refusal that describes work an agent has not done rather than a
    definition that is wrong. The default story is that a stage names no
    cases and the responsible agent chooses or creates them, so a caller
    must be able to tell "nobody has selected cases yet" — a durable wait
    that should wake that agent — from an invalid pinned plan, an
    unresolvable target identity, or a permission failure, all of which
    are real stage failures. Collapsing them would either strand the
    agent or dress a broken definition up as patience.
    """


def _selected_plans(
    conn: Any,
    subject: Mapping[str, Any],
    *,
    agent_plan: str | None,
    target: Mapping[str, Any],
    allow_empty: bool = False,
) -> list[dict[str, Any]]:
    frozen = [*_flow_plan(subject), *_member_plans(subject, target=target)]
    if not frozen:
        # Nothing pinned or frozen selected cases, so the member's own
        # attached plan answers before any --plan choice is needed.
        frozen = attached_member_plans(conn, subject, target=target)
    configured = isinstance(subject["stage"].get("cases"), Mapping)
    if configured and agent_plan is not None:
        raise QaPlanError(
            "this deployment QA stage pins its cases; omit the agent-selected plan"
        )
    if agent_plan is not None:
        row = conn.execute(
            "SELECT id FROM qa_plans WHERE project_id=%s "
            "AND (slug=%s OR CAST(id AS TEXT)=%s) AND retired_at IS NULL",
            (int(subject["project_id"]), str(agent_plan), str(agent_plan)),
        ).fetchone()
        if row is None:
            raise QaPlanError(
                f"agent-selected QA plan {agent_plan!r} is not active in this project"
            )
        agent_plan_id = int(row["id"] if hasattr(row, "keys") else row[0])
        frozen.append(
            _plan_snapshot(
                conn,
                int(agent_plan_id),
                project_id=int(subject["project_id"]),
            )
        )
    unique: dict[tuple[int, tuple[str, ...]], dict[str, Any]] = {}
    for snapshot in frozen:
        plan = snapshot.get("plan")
        cases = snapshot.get("cases")
        if not isinstance(plan, Mapping) or not isinstance(cases, list):
            raise QaPlanError("frozen deployment QA plan snapshot is invalid")
        key = (
            int(plan["id"]),
            tuple(str(case["case_key"]) for case in cases if isinstance(case, Mapping)),
        )
        unique[key] = snapshot
    if not unique and not allow_empty:
        raise QaCasesNotSelectedError(
            "deployment QA stage has no pinned cases; select a project QA "
            "plan and retry, naming the same stage (and member, on an "
            "item-scoped stage) this execution runs under: `yoke qa plan run "
            "--deployment-run-id RUN --stage STAGE [--member PREFIX-N] "
            "--plan PLAN --project P`"
        )
    return list(unique.values())


def _existing_rows(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    plan_id: int,
    execution_target_digest: str,
) -> list[dict[str, Any]]:
    return query_rows(
        conn,
        "SELECT id,execution_target_json,execution_target_digest "
        "FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s AND plan_id=%s "
        "AND execution_target_digest=%s ORDER BY id",
        (
            run_id,
            stage_name,
            member_item_id or 0,
            int(plan_id),
            execution_target_digest,
        ),
    )


def materialize_deployment_qa_stage(
    conn: Any,
    *,
    deployment_run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None = None,
    agent_plan: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Create concrete scoped cases from the run's immutable snapshots."""
    subject = deployment_qa_stage_subject(
        conn,
        run_id=deployment_run_id,
        stage_name=deployment_stage,
        member_item_id=deployment_member_item_id,
    )
    target = deployment_qa_execution_target(conn, subject)
    admitted = member_requirements(subject, target=target)
    snapshots = _selected_plans(
        conn,
        subject,
        agent_plan=agent_plan,
        target=target,
        allow_empty=True,
    )
    created: list[int] = []
    existing: list[int] = []
    now = iso8601_now()
    try:
        # Serializes first materialization without adding another ledger/index.
        conn.execute(
            "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE",
            (str(deployment_run_id),),
        )
        bound_direct = bind_existing_direct_deployment_cases(
            conn, subject=subject, target=target
        )
        if not (
            snapshots
            or bound_direct
            or any(requirement.get("method_id") for requirement in admitted)
        ):
            raise QaCasesNotSelectedError(
                "deployment QA stage has no pinned cases; select a project QA "
                "plan and retry, naming the same stage (and member, on an "
                "item-scoped stage) this execution runs under: `yoke qa plan "
                "run --deployment-run-id RUN --stage STAGE [--member "
                "PREFIX-N] --plan PLAN --project P`"
            )
        existing.extend(bound_direct)
        for position, requirement in enumerate(admitted, start=1):
            requirement_id, was_created = materialize_admitted_requirement(
                conn,
                subject=subject,
                requirement=requirement,
                position=position,
                target=target,
                now=now,
            )
            (created if was_created else existing).append(requirement_id)
        for snapshot in snapshots:
            plan = dict(snapshot["plan"])
            plan_id = int(plan["id"])
            rows = _existing_rows(
                conn,
                run_id=str(deployment_run_id),
                stage_name=str(deployment_stage),
                member_item_id=deployment_member_item_id,
                plan_id=plan_id,
                execution_target_digest=target_digest(target),
            )
            refreshed = refreshed_case_keys(
                conn,
                run_id=str(deployment_run_id),
                stage_name=str(deployment_stage),
                member_item_id=deployment_member_item_id,
                plan_id=plan_id,
                execution_target_digest=target_digest(target),
                cases=[dict(case) for case in snapshot["cases"]],
            )
            if rows and not refreshed:
                existing.extend(
                    require_existing_target(
                        rows,
                        execution_target=target,
                        subject=(
                            f"deployment run {deployment_run_id!r} stage "
                            f"{deployment_stage!r} member {deployment_member_item_id!r}"
                        ),
                    )
                )
                continue
            attachment = {"qa_phase": "post_deploy"}
            for case_value in snapshot["cases"]:
                case = dict(case_value)
                if rows:
                    # Already-materialized plan: only the cases whose content
                    # changed after their row stopped answering get a fresh
                    # row, and they take a key distinct from the frozen one.
                    fresh_key = refreshed.get(str(case["case_key"]))
                    if fresh_key is None:
                        continue
                    case["case_key"] = fresh_key
                raw_baselines = case.get("host_baselines") or []
                baselines = (
                    list(raw_baselines)
                    if isinstance(raw_baselines, list)
                    else json.loads(str(raw_baselines))
                ) or [None]
                for position, baseline in enumerate(baselines, start=1):
                    requirement_id = insert_requirement(
                        conn,
                        deployment_run_id=str(deployment_run_id),
                        deployment_stage=str(deployment_stage),
                        deployment_member_item_id=deployment_member_item_id,
                        plan=plan,
                        attachment=attachment,
                        case=case,
                        baseline=baseline,
                        baseline_position=position,
                        now=now,
                        execution_target=target,
                    )
                    if requirement_id is not None:
                        created.append(requirement_id)
                        continue
                    winner = existing_requirement_id(
                        conn,
                        deployment_run_id=str(deployment_run_id),
                        deployment_stage=str(deployment_stage),
                        deployment_member_item_id=deployment_member_item_id,
                        plan_id=plan_id,
                        case_key=str(case["case_key"]),
                        baseline=baseline,
                        execution_target_digest=target_digest(target),
                    )
                    if winner is not None:
                        existing.append(
                            require_requirement_id_target(
                                conn,
                                requirement_id=winner,
                                execution_target=target,
                                subject=f"deployment stage {deployment_stage!r}",
                            )
                        )
        if commit:
            conn.commit()
    except Exception:
        if commit:
            conn.rollback()
        raise
    return {
        "deployment_run_id": str(deployment_run_id),
        "deployment_stage": str(deployment_stage),
        "deployment_member_item_id": deployment_member_item_id,
        "candidate_revision": str(subject["release_lineage"]),
        "execution_target": target,
        "created_requirement_ids": created,
        "existing_requirement_ids": existing,
    }


__all__ = [
    "QaCasesNotSelectedError",
    "materialize_deployment_qa_stage",
]

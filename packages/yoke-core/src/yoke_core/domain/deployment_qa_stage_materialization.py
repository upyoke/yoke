"""Materialize frozen deployment QA cases onto scoped requirements."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
from yoke_core.domain.deployment_qa_frozen_plan_selection import (
    frozen_stage_plans,
    member_requirements,
)
from yoke_core.domain.qa_deployment_case_content_refresh import (
    base_case_key,
    declare_refreshed_replacements,
    refreshed_case_keys,
)
from yoke_core.domain.db_helpers import iso8601_now, query_rows
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.deployment_qa_stage_named_cases import (
    AGENT_PLAN_ALREADY_NAMED_REFUSAL,
    require_correction_only_plan,
    stage_names_cases,
)
from yoke_core.domain.deployment_qa_admission_materialization import (
    materialize_admitted_requirement,
)
from yoke_core.domain.deployment_qa_direct_case_target import (
    bind_existing_direct_deployment_cases,
)
from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
from yoke_core.domain.post_deploy_verification_answer import (
    cases_not_selected_refusal,
    NOT_REQUIRED,
    member_post_deploy_answer,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_case_definition import snapshot_fan_out
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    require_existing_target,
    require_requirement_id_target,
)


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
    admitted: list[dict[str, Any]],
    allow_empty: bool = False,
    replacement_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    frozen = frozen_stage_plans(conn, subject, target=target, admitted=admitted)
    named = agent_plan is not None and stage_names_cases(
        conn, subject, frozen_plans=frozen, admitted=admitted
    )
    if named and not replacement_keys:
        raise QaPlanError(AGENT_PLAN_ALREADY_NAMED_REFUSAL)
    if agent_plan is not None:
        plan_project_id = int(subject.get("member_project_id") or subject["project_id"])
        row = conn.execute(
            "SELECT id FROM qa_plans WHERE project_id=%s "
            "AND (slug=%s OR CAST(id AS TEXT)=%s) AND retired_at IS NULL",
            (plan_project_id, str(agent_plan), str(agent_plan)),
        ).fetchone()
        if row is None:
            raise QaPlanError(
                f"agent-selected QA plan {agent_plan!r} is not active in this project"
            )
        agent_plan_id = int(row["id"] if hasattr(row, "keys") else row[0])
        snapshot = _plan_snapshot(conn, int(agent_plan_id), project_id=plan_project_id)
        if named:
            require_correction_only_plan(snapshot, replacement_keys or set())
        frozen.append(snapshot)
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
        raise QaCasesNotSelectedError(cases_not_selected_refusal())
    from yoke_core.domain.qa_plan_case_targets import case_applies_to_target

    return [
        {**snapshot, "cases": cases}
        for snapshot in unique.values()
        if (
            cases := [
                case
                for case in snapshot["cases"]
                if case_applies_to_target(case, target)
            ]
        )
    ]


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
        "SELECT id,plan_case_key,execution_target_json,execution_target_digest "
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
    replacement_keys: set[str] | None = None,
    replaced_requirement_ids: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """Create concrete scoped cases from the run's immutable snapshots."""
    subject = deployment_qa_stage_subject(
        conn,
        run_id=deployment_run_id,
        stage_name=deployment_stage,
        member_item_id=deployment_member_item_id,
    )
    target = deployment_qa_execution_target(conn, subject)
    admitted = member_requirements(conn, subject, target=target)
    snapshots = _selected_plans(
        conn,
        subject,
        agent_plan=agent_plan,
        target=target,
        admitted=admitted,
        allow_empty=True,
        replacement_keys=replacement_keys,
    )
    created: list[int] = []
    existing: list[int] = []
    declared_none: tuple[str, ...] = ()
    not_required: tuple[str, ...] = ()
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
            # Recorded emptiness or the own-flow exemption settles no cases;
            # other unanswered members still wait.
            answer = member_post_deploy_answer(conn, subject)
            if not answer.discharges_without_cases:
                raise QaCasesNotSelectedError(cases_not_selected_refusal())
            if answer.verdict == NOT_REQUIRED:
                not_required = answer.reasons
            else:
                declared_none = answer.reasons
        existing.extend(bound_direct)
        for requirement in admitted:
            if requirement.get("plan_id") is not None:
                continue  # Its ordered cases are materialized through snapshots below.
            requirement_id, was_created = materialize_admitted_requirement(
                conn,
                subject=subject,
                requirement=requirement,
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
                explicitly_replaced=replaced_requirement_ids,
            )
            materialized_keys = {base_case_key(row["plan_case_key"]) for row in rows}
            added = any(
                str(case["case_key"]) not in materialized_keys
                for case in snapshot["cases"]
            )
            if rows and not refreshed and not added:
                existing.extend(
                    require_existing_target(
                        rows,
                        execution_target=target,
                        subject=(
                            f"deployment run {deployment_run_id!r} stage "
                            f"{deployment_stage!r} member {deployment_member_item_id!r}"
                        ),
                        conn=conn,
                    )
                )
                continue
            attachment = {"qa_phase": "post_deploy"}
            fan_out = snapshot_fan_out(plan, snapshot["cases"])
            for case_value in snapshot["cases"]:
                case = dict(case_value)
                baselines = fan_out[str(case["case_key"])]
                if rows:
                    # Already-materialized plan: a case added since gets its
                    # first row under its own key; of the rest, only a case
                    # whose content changed after its row stopped answering
                    # gets a fresh row, keyed apart from the frozen one.
                    fresh_key = refreshed.get(str(case["case_key"]))
                    if fresh_key is not None:
                        case["case_key"] = fresh_key
                    elif str(case["case_key"]) in materialized_keys:
                        continue
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
        declare_refreshed_replacements(conn, created)
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
        # The commit the run delivered for the member's project: a member
        # carried from a bound project is checked against that build.
        "candidate_revision": run_delivered_sha(
            conn, str(deployment_run_id), int(target["project"]["id"])
        ),
        "execution_target": target,
        "created_requirement_ids": created,
        "existing_requirement_ids": existing,
        # Non-empty only for a member that recorded it needs no post-deploy
        # verification, so a reader can tell a stage that credited nothing
        # deliberately from one that found work to do.
        "declared_no_post_deploy_verification": list(declared_none),
        "no_item_qa_obligation": list(not_required),
    }


__all__ = [
    "QaCasesNotSelectedError",
    "materialize_deployment_qa_stage",
]

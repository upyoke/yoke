"""Materialize frozen deployment QA cases onto scoped requirements."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.qa_deployment_requirement_identity_schema import shared_group_id
from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
from yoke_core.domain.qa_deployment_case_content_refresh import (
    declare_refreshed_replacements,
    refreshed_case_keys,
)
from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.qa_requirement_lineage import rows_by_case
from yoke_core.domain.deployment_qa_admission_materialization import (
    materialize_admitted_requirement,
)
from yoke_core.domain.deployment_qa_direct_case_target import (
    bind_existing_direct_deployment_cases,
)
from yoke_core.domain.post_deploy_verification_answer import (
    cases_not_selected_refusal,
    NOT_REQUIRED,
    PLAN_GROUPS,
    member_post_deploy_answer,
)
from yoke_core.domain.qa_plan_case_definition import snapshot_fan_out
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    require_requirement_id_target,
)


def materialize_subject(
    conn: Any,
    *,
    subject: dict,
    target: dict,
    admitted: list[dict],
    snapshots: list[dict],
    commit: bool = True,
    replaced_requirement_ids: frozenset[int] = frozenset(),
    refresh_target: bool = True,
) -> dict[str, Any]:
    """Materialize one member's cases, a run subject, or one plan group."""
    from yoke_core.domain.deployment_qa_stage_materialization import (
        QaCasesNotSelectedError,
    )

    deployment_run_id = str(subject["id"])
    deployment_stage = str(subject["stage"]["name"])
    deployment_member_item_id = subject.get("member_item_id")
    created: list[int] = []
    existing: list[int] = []
    declared_none: tuple[str, ...] = ()
    not_required: tuple[str, ...] = ()
    now = utc_now()
    try:
        # Serializes first materialization without adding another ledger/index.
        lock_run(conn, str(deployment_run_id))
        from yoke_core.domain.deployment_qa_requirement_target_refresh import (
            rebind_subject,
        )

        if refresh_target:
            rebind_subject(conn, subject=subject, target=target)
        from yoke_core.domain.deployment_qa_snapshot_selection import (
            freeze_selected_plans,
        )

        freeze_selected_plans(conn, subject, snapshots)
        bound_direct = (
            []
            if subject.get("shared_plan")
            else bind_existing_direct_deployment_cases(
                conn, subject=subject, target=target
            )
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
            elif answer.verdict == PLAN_GROUPS:
                pass
            else:
                declared_none = answer.reasons
        existing.extend(bound_direct)
        for requirement in admitted:
            if (
                not requirement.get("method_id")
                or requirement.get("plan_id") is not None
            ):
                continue  # Only executable, plan-less obligations need a copy.
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
            groups = rows_by_case(
                conn,
                run_id=deployment_run_id,
                stage_name=deployment_stage,
                member_item_id=deployment_member_item_id,
                plan_id=plan_id,
                group_id=shared_group_id(target),
            )
            existing.extend(
                {int(head["id"]) for heads in groups.values() for head in heads}
            )
            refreshed = refreshed_case_keys(
                conn,
                run_id=deployment_run_id,
                stage_name=deployment_stage,
                member_item_id=deployment_member_item_id,
                plan_id=plan_id,
                execution_target_digest=target_digest(target),
                group_id=shared_group_id(target),
                cases=[dict(case) for case in snapshot["cases"]],
                explicitly_replaced=(
                    frozenset()
                    if snapshot.get("corrects_own_plan")
                    else replaced_requirement_ids
                ),
            )
            attachment = {"qa_phase": "post_deploy"}
            fan_out = snapshot_fan_out(plan, snapshot["cases"])
            for case_value in snapshot["cases"]:
                case = dict(case_value)
                baselines = fan_out[str(case["case_key"])]
                for position, baseline in enumerate(baselines, start=1):
                    key = (str(case_value["case_key"]), baseline)
                    fresh_key = refreshed.get(key)
                    if key in groups and fresh_key is None:
                        continue
                    case = {
                        **dict(case_value),
                        "case_key": fresh_key or case_value["case_key"],
                    }
                    scopes = snapshot.get("replacement_scopes", {}).get(
                        str(case_value["case_key"])
                    )
                    if scopes and not any(
                        scope["host_baseline"] == baseline for scope in scopes
                    ):
                        continue
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
                        group_id=shared_group_id(target),
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

"""Materialize frozen deployment QA cases onto scoped requirements."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
from yoke_core.domain.qa_deployment_case_content_refresh import (
    base_case_key,
    declare_refreshed_replacements,
    refreshed_case_keys,
)
from yoke_core.domain.db_helpers import utc_now, query_rows
from yoke_core.domain.deployment_qa_admission_materialization import (
    materialize_admitted_requirement,
)
from yoke_core.domain.deployment_qa_direct_case_target import (
    bind_existing_direct_deployment_cases,
)
from yoke_core.domain.post_deploy_verification_answer import (
    cases_not_selected_refusal,
    NOT_REQUIRED,
    member_post_deploy_answer,
)
from yoke_core.domain.qa_plan_case_definition import snapshot_fan_out
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    require_existing_target,
    require_requirement_id_target,
)


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


def materialize_subject(
    conn: Any,
    *,
    subject: dict,
    target: dict,
    admitted: list[dict],
    snapshots: list[dict],
    commit: bool = True,
    replaced_requirement_ids: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    """Materialize one concrete private or shared QA subject."""
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
        conn.execute(
            "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE",
            (str(deployment_run_id),),
        )
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
            from yoke_core.domain.deployment_qa_shared_copy_reads import (
                withdrawn_member_discharge,
            )

            if not answer.discharges_without_cases and not withdrawn_member_discharge(
                conn, subject, target
            ):
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
                            f"{deployment_stage!r} member {render_item_ref(conn, deployment_member_item_id) if deployment_member_item_id is not None else 'run'}"
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

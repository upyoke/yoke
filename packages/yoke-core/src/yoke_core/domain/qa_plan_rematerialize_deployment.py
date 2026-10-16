"""Refresh pending deployment cases and their existing frozen selection atomically."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.deployment_qa_shared_corrections import route_shared_refresh
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.db_helpers import instant_parameter, utc_now, query_rows
from yoke_core.domain.qa_deployment_case_correction_window import (
    determinate_verdict,
)
from yoke_core.domain.qa_deployment_case_content_refresh import (
    base_case_key,
    carried_by_declared_replacement,
    case_content_digest,
    declare_refreshed_replacements,
    refreshed_case_key,
)
from yoke_core.domain.qa_obligation_settlement import (
    obligation_settled,
    requirement_retracted_at_select,
)
from yoke_core.domain.qa_plan_case_definition import case_baselines, plan_cases
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder, _plan_row
from yoke_core.domain.qa_plan_refresh_safety import require_no_live_execution
from yoke_core.domain.qa_plan_rematerialize import REPLACEMENT_RATIONALE
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    refresh_requirement,
)
from yoke_core.domain.deployment_qa_snapshot_correction import (
    selected_plan_owners,
    refresh_selected_cases,
)
from yoke_core.domain.workflow_item_binding_lock import (
    rollback_workflow_binding_write_errors,
)


_DEPLOYMENT_ATTACHMENT = {"qa_phase": "post_deploy"}


def _scoped_rows(
    conn: Any,
    *,
    deployment_run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None,
) -> list[dict[str, Any]]:
    marker = _placeholder(conn)
    return [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT id,plan_id,plan_case_key,host_baseline,waived_at,"
            "superseded_by_requirement_id,replacement_requirement_id,"
            "execution_target_json,execution_target_digest,method_id,method_config,instructions,"
            f"expected_outcome,{requirement_retracted_at_select(conn)} "
            "FROM qa_requirements "
            f"WHERE deployment_run_id={marker} AND deployment_stage={marker} "
            f"AND COALESCE(deployment_member_item_id,0)={marker} "
            "AND plan_id IS NOT NULL ORDER BY id",
            (
                str(deployment_run_id),
                str(deployment_stage),
                int(deployment_member_item_id or 0),
            ),
        )
    ]


def _pinned_target(rows: list[dict[str, Any]], *, subject: str) -> dict[str, Any]:
    """The one target every row in this subject is already judged against."""
    digests = {str(row["execution_target_digest"] or "") for row in rows}
    if len(digests) != 1 or not next(iter(digests)):
        raise QaPlanError(
            f"{subject} has ambiguous materialized target history "
            f"({len(digests)} distinct targets); select an attaching --member or resolve it against the active "
            "stage receipt before rematerializing"
        )
    raw = rows[0]["execution_target_json"]
    if isinstance(raw, dict):
        return dict(raw)
    try:
        decoded = json.loads(str(raw or ""))
    except (TypeError, ValueError) as exc:
        raise QaPlanError(f"{subject} has an unreadable execution target") from exc
    if not isinstance(decoded, dict):
        raise QaPlanError(f"{subject} execution target is not an object")
    return decoded


def _needs_corrected_row(
    conn: Any, case: Mapping[str, Any], group: list[dict[str, Any]]
) -> bool:
    """New or changed failed/discharged cases owe a row; passed cases stand."""
    if not group:
        return True
    if carried_by_declared_replacement(conn, group):
        return False
    digest = case_content_digest(case)
    if any(case_content_digest(row) == digest for row in group):
        return False
    return all(
        obligation_settled(row) or determinate_verdict(conn, int(row["id"])) == "fail"
        for row in group
    )


def _insert_case(
    conn: Any,
    *,
    subject: str,
    deployment_run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None,
    plan: Any,
    case: Mapping[str, Any],
    baseline: Any,
    baseline_position: int,
    execution_target: dict[str, Any],
) -> int:
    scope = {
        "deployment_run_id": deployment_run_id,
        "deployment_stage": deployment_stage,
        "deployment_member_item_id": deployment_member_item_id,
    }
    inserted = insert_requirement(
        conn,
        **scope,
        plan=plan,
        attachment=_DEPLOYMENT_ATTACHMENT,
        case=case,
        baseline=baseline,
        baseline_position=baseline_position,
        now=utc_now(),
        execution_target=execution_target,
    )
    if inserted is None:
        inserted = existing_requirement_id(
            conn,
            **scope,
            plan_id=int(plan["id"]),
            case_key=str(case["case_key"]),
            baseline=baseline,
            execution_target_digest=target_digest(execution_target),
        )
    if inserted is None:
        raise QaPlanError(f"{subject} could not materialize case {case['case_key']!r}")
    return int(inserted)


@route_shared_refresh
@rollback_workflow_binding_write_errors
def rematerialize_for_deployment_stage(
    conn: Any,
    *,
    deployment_run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None = None,
    plan: str | int | None = None,
    commit: bool = True,
    _execution_target_digest: str | None = None,
    _selection_member_item_id: int | None = None,
) -> dict[str, Any]:
    """Refresh this subject's plan cases from their current plan definitions."""
    subject = (
        f"deployment run {str(deployment_run_id)!r} stage "
        f"{str(deployment_stage)!r} member {render_item_ref(conn, deployment_member_item_id) if deployment_member_item_id is not None else 'run'}"
    )
    conn.execute(
        "SELECT id FROM deployment_runs WHERE id=%s FOR UPDATE", (deployment_run_id,)
    ).fetchone()
    rows = _scoped_rows(
        conn,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    if _execution_target_digest is not None:
        rows = [
            row
            for row in rows
            if row["execution_target_digest"] == _execution_target_digest
        ]
    if not rows:
        raise QaPlanError(
            f"{subject} has no materialized plan cases to refresh; materialize "
            "the plan onto the stage first"
        )
    execution_target = _pinned_target(rows, subject=subject)
    # Refused before the first write: half a refresh is worse than none.
    require_no_live_execution(
        conn,
        subject=subject,
        deployment_run_id=str(deployment_run_id),
        deployment_stage=str(deployment_stage),
        deployment_member_item_id=deployment_member_item_id,
    )

    rows_by_plan: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_plan.setdefault(int(row["plan_id"]), []).append(row)
    if plan is not None:
        selected = {
            plan_id
            for plan_id in rows_by_plan
            if str(plan_id) == str(plan)
            or str(_plan_row(conn, plan_id)["slug"]) == str(plan)
        }
        if not selected:
            raise QaPlanError(f"{subject} has no materialized cases from plan {plan!r}")
        rows_by_plan = {
            plan_id: plan_rows
            for plan_id, plan_rows in rows_by_plan.items()
            if plan_id in selected
        }

    from yoke_core.domain.qa_plan_source_revision import require_candidate_plan

    for plan_id in rows_by_plan:
        require_candidate_plan(conn, _plan_row(conn, plan_id), str(deployment_run_id))
        selected_plan_owners(
            conn,
            run_id=deployment_run_id,
            stage=deployment_stage,
            plan_id=plan_id,
            member_item_id=_selection_member_item_id or deployment_member_item_id,
            shared_target_digest=_execution_target_digest,
        )
    created: list[int] = []
    refreshed: list[int] = []
    retained: set[int] = set()
    for plan_id, plan_rows in rows_by_plan.items():
        plan_row = _plan_row(conn, plan_id)
        groups: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        for row in plan_rows:
            groups.setdefault(
                (base_case_key(row["plan_case_key"]), row["host_baseline"]), []
            ).append(row)
        from yoke_core.domain.qa_plan_case_targets import case_applies_to_target

        cases = plan_cases(conn, plan_id)
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be rematerialized"
            )
        cases = [
            case for case in cases if case_applies_to_target(case, execution_target)
        ]
        corrected_cases = []
        for case in cases:
            corrected = False
            for baseline_position, baseline in enumerate(case_baselines(case), start=1):
                group = groups.get((str(case["case_key"]), baseline), [])
                retained.update(int(row["id"]) for row in group)
                live = [
                    row
                    for row in group
                    if not obligation_settled(row)
                    and not determinate_verdict(conn, int(row["id"]))
                ]
                for row in live:
                    # A corrected row keeps the distinct key it was minted
                    # under; only its content follows the plan.
                    refresh_requirement(
                        conn,
                        requirement_id=int(row["id"]),
                        transition_id=None,
                        plan=plan_row,
                        attachment=_DEPLOYMENT_ATTACHMENT,
                        case={**dict(case), "case_key": row["plan_case_key"]},
                        baseline=baseline,
                        baseline_position=baseline_position,
                        execution_target=execution_target,
                    )
                    refreshed.append(int(row["id"]))
                    corrected = True
                if live or not _needs_corrected_row(conn, case, group):
                    continue
                key = str(case["case_key"])
                if group:
                    key = refreshed_case_key(key, case_content_digest(case))
                created.append(
                    _insert_case(
                        conn,
                        subject=subject,
                        deployment_run_id=str(deployment_run_id),
                        deployment_stage=str(deployment_stage),
                        deployment_member_item_id=deployment_member_item_id,
                        plan=plan_row,
                        case={**dict(case), "case_key": key},
                        baseline=baseline,
                        baseline_position=baseline_position,
                        execution_target=execution_target,
                    )
                )
                corrected = True
            if corrected:
                corrected_cases.append(case)
        if corrected_cases:
            refresh_selected_cases(
                conn,
                run_id=deployment_run_id,
                stage=deployment_stage,
                plan_id=plan_id,
                member_item_id=_selection_member_item_id or deployment_member_item_id,
                cases=corrected_cases,
                allow_added=True,
                shared_target_digest=_execution_target_digest,
            )
    declare_refreshed_replacements(conn, created)
    waived = [
        int(row["id"])
        for plan_rows in rows_by_plan.values()
        for row in plan_rows
        if int(row["id"]) not in retained and not obligation_settled(row)
    ]
    for requirement_id in waived:
        conn.execute(
            "UPDATE qa_requirements SET waived_at=%s, waiver_rationale=%s, "
            "waiver_source=%s WHERE id=%s",
            (
                instant_parameter(conn, utc_now()),
                REPLACEMENT_RATIONALE,
                "system",
                requirement_id,
            ),
        )
    if commit:
        conn.commit()
    return {
        "deployment_run_id": str(deployment_run_id),
        "deployment_stage": str(deployment_stage),
        "deployment_member_item_id": deployment_member_item_id,
        "plan_ids": sorted(rows_by_plan),
        "created_requirement_ids": created,
        "refreshed_requirement_ids": refreshed,
        "waived_requirement_ids": waived,
    }


__all__ = ["rematerialize_for_deployment_stage"]

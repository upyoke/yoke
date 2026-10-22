"""Read, then refresh, one deployment QA subject's cases from current plans.

The read takes no lock: the subject's rows, its pinned target, the current
plan definitions and each row's settled verdict. The write runs under the
run row lock once the caller proved the read still current.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, query_rows, utc_now
from yoke_core.domain.deployment_qa_snapshot_correction import (
    refresh_selected_cases,
    selected_plan_owners,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_deployment_case_content_refresh import (
    base_case_key,
    carried_by_declared_replacement,
    case_content_digest,
    declare_refreshed_replacements,
    plan_case_content_digest,
    refreshed_case_key,
)
from yoke_core.domain.qa_deployment_case_correction_window import (
    determinate_verdicts,
)
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_obligation_settlement import (
    obligation_settled,
    requirement_retracted_at_select,
)
from yoke_core.domain.qa_plan_case_definition import case_baselines, plan_cases
from yoke_core.domain.qa_plan_case_targets import case_applies_to_target
from yoke_core.domain.qa_plan_management import QaPlanError, _plan_row
from yoke_core.domain.qa_plan_refresh_safety import carry_into_live_rosters
from yoke_core.domain.qa_plan_rematerialize import REPLACEMENT_RATIONALE
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    refresh_requirement,
)

_DEPLOYMENT_ATTACHMENT = {"qa_phase": "post_deploy"}


@dataclass
class SubjectRefresh:
    """One private subject or exact shared group, read before the run lock."""

    label: str
    run_id: str
    stage: str
    member: int | None
    selection_member: int | None
    shared_digest: str | None
    target: dict
    rows_by_plan: dict[int, list[dict]]
    plans: dict[int, tuple[Any, list[dict]]]
    verdicts: dict[int, str]


def _pinned_target(rows: list[dict[str, Any]], *, subject: str) -> dict[str, Any]:
    """The one target every row in this subject is already judged against."""
    digests = {str(row["execution_target_digest"] or "") for row in rows}
    if len(digests) != 1 or not next(iter(digests)):
        raise QaPlanError(
            f"{subject} has ambiguous materialized target history ({len(digests)} "
            "distinct targets); select an attaching --item or resolve it against "
            "the active stage receipt before rematerializing"
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


def read_subject_refresh(
    conn: Any,
    *,
    run_id: str,
    stage: str,
    member: int | None,
    plan: str | int | None,
    shared_digest: str | None = None,
    selection_member: int | None = None,
) -> SubjectRefresh:
    """Every fact one subject's refresh needs, read without a lock."""
    from yoke_core.domain.qa_plan_source_revision import require_candidate_plan

    label = (
        f"deployment run {run_id!r} stage {stage!r} member "
        f"{render_item_ref(conn, member) if member is not None else 'run'}"
    )
    rows = [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT id,plan_id,plan_case_key,host_baseline,waived_at,"
            "superseded_by_requirement_id,replacement_requirement_id,"
            "execution_target_json,execution_target_digest,method_id,method_config,"
            f"instructions,expected_outcome,{requirement_retracted_at_select(conn)} "
            "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
            "AND COALESCE(deployment_member_item_id,0)=%s AND plan_id IS NOT NULL "
            "ORDER BY id",
            (run_id, stage, int(member or 0)),
        )
        if shared_digest is None or row["execution_target_digest"] == shared_digest
    ]
    if not rows:
        raise QaPlanError(
            f"{label} has no materialized plan cases to refresh; materialize "
            "the plan onto the stage first"
        )
    target = _pinned_target(rows, subject=label)
    rows_by_plan: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_plan.setdefault(int(row["plan_id"]), []).append(row)
    plan_rows = {plan_id: _plan_row(conn, plan_id) for plan_id in rows_by_plan}
    if plan is not None:
        rows_by_plan = {
            plan_id: plan_rows_
            for plan_id, plan_rows_ in rows_by_plan.items()
            if str(plan) in {str(plan_id), str(plan_rows[plan_id]["slug"])}
        }
        if not rows_by_plan:
            raise QaPlanError(f"{label} has no materialized cases from plan {plan!r}")
    plans = {}
    for plan_id in rows_by_plan:
        require_candidate_plan(conn, plan_rows[plan_id], run_id)
        cases = plan_cases(conn, plan_id)
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be rematerialized"
            )
        plans[plan_id] = (
            plan_rows[plan_id],
            [case for case in cases if case_applies_to_target(case, target)],
        )
    return SubjectRefresh(
        label=label,
        run_id=run_id,
        stage=stage,
        member=member,
        selection_member=selection_member or member,
        shared_digest=shared_digest,
        target=target,
        rows_by_plan=rows_by_plan,
        plans=plans,
        verdicts=determinate_verdicts(
            conn, [row["id"] for rows_ in rows_by_plan.values() for row in rows_]
        ),
    )


def _needs_corrected_row(
    conn: Any, refresh: SubjectRefresh, case: Mapping[str, Any], group: list[dict]
) -> bool:
    """New or changed failed/discharged cases owe a row; passed cases stand."""
    if not group:
        return True
    if carried_by_declared_replacement(conn, group):
        return False
    digest = plan_case_content_digest(conn, case)
    if any(case_content_digest(row) == digest for row in group):
        return False
    return all(
        obligation_settled(row) or refresh.verdicts.get(int(row["id"])) == "fail"
        for row in group
    )


def _insert_case(conn, refresh, *, plan, case, baseline, position) -> int:
    scope = {
        "deployment_run_id": refresh.run_id,
        "deployment_stage": refresh.stage,
        "deployment_member_item_id": refresh.member,
    }
    inserted = insert_requirement(
        conn,
        **scope,
        plan=plan,
        attachment=_DEPLOYMENT_ATTACHMENT,
        case=case,
        baseline=baseline,
        baseline_position=position,
        now=utc_now(),
        execution_target=refresh.target,
    )
    if inserted is None:
        inserted = existing_requirement_id(
            conn,
            **scope,
            plan_id=int(plan["id"]),
            case_key=str(case["case_key"]),
            baseline=baseline,
            execution_target_digest=target_digest(refresh.target),
        )
    if inserted is None:
        raise QaPlanError(
            f"{refresh.label} could not materialize case {case['case_key']!r}"
        )
    return int(inserted)


def write_subject_refresh(
    conn: Any, refresh: SubjectRefresh, *, group_digests
) -> dict[str, Any]:
    """Refresh this subject's rows; the caller holds the run lock."""
    owner_scope = dict(
        run_id=refresh.run_id,
        stage=refresh.stage,
        member_item_id=refresh.selection_member,
        shared_target_digest=refresh.shared_digest,
        group_digests=group_digests,
    )
    for plan_id in refresh.rows_by_plan:
        selected_plan_owners(conn, plan_id=plan_id, **owner_scope)
    created: list[int] = []
    refreshed: list[int] = []
    retained: set[int] = set()
    for plan_id, plan_rows in refresh.rows_by_plan.items():
        plan_row, cases = refresh.plans[plan_id]
        groups: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        for row in plan_rows:
            key = (base_case_key(row["plan_case_key"]), row["host_baseline"])
            groups.setdefault(key, []).append(row)
        corrected_cases = []
        for case in cases:
            corrected = False
            for position, baseline in enumerate(case_baselines(case), start=1):
                group = groups.get((str(case["case_key"]), baseline), [])
                retained.update(int(row["id"]) for row in group)
                live = [
                    row
                    for row in group
                    if not obligation_settled(row)
                    and not refresh.verdicts.get(int(row["id"]))
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
                        baseline_position=position,
                        execution_target=refresh.target,
                    )
                    refreshed.append(int(row["id"]))
                    corrected = True
                if live or not _needs_corrected_row(conn, refresh, case, group):
                    continue
                key = str(case["case_key"])
                if group:
                    key = refreshed_case_key(key, plan_case_content_digest(conn, case))
                created.append(
                    _insert_case(
                        conn,
                        refresh,
                        plan=plan_row,
                        case={**dict(case), "case_key": key},
                        baseline=baseline,
                        position=position,
                    )
                )
                corrected = True
            if corrected:
                corrected_cases.append(case)
        if corrected_cases:
            refresh_selected_cases(
                conn,
                plan_id=plan_id,
                cases=corrected_cases,
                allow_added=True,
                **owner_scope,
            )
    declare_refreshed_replacements(conn, created)
    waived = [
        int(row["id"])
        for plan_rows in refresh.rows_by_plan.values()
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
    carry_into_live_rosters(
        conn,
        subject=refresh.label,
        rewritten=[*refreshed, *waived],
        created=created,
        deployment_run_id=refresh.run_id,
        deployment_stage=refresh.stage,
        deployment_member_item_id=refresh.member,
    )
    return {
        "plan_ids": sorted(refresh.rows_by_plan),
        "created_requirement_ids": created,
        "refreshed_requirement_ids": refreshed,
        "waived_requirement_ids": waived,
    }


__all__ = ["SubjectRefresh", "read_subject_refresh", "write_subject_refresh"]

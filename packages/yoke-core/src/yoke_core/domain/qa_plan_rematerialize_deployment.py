"""Refresh an already-materialized deployment stage's cases from its plan.

:mod:`qa_plan_rematerialize` does this for an item transition. A deployment
run, stage and member subject had no equivalent, and one unique index is why
it mattered: a materialized case is unique on
``(run, stage, member, plan_id, plan_case_key, host_baseline, target)``, so a
corrected plan case could never arrive as a second row. Correcting a case
meant publishing a whole new plan, or giving up and waiving the broken one.

Refreshing in place is the fix, bounded by what a run-bound case owes. A case
that has not recorded a determinate verdict is a case nobody has judged, so
its content is refreshed from the plan exactly as the item path does. A case
that has answered is an acceptance record, so this refuses rather than
rewriting it, and names the corrected-case route
(:mod:`qa_requirement_supersession`) for that row.

The subject's target is never moved. A deployment row is pinned to the target
its stage receipt observed, so every refresh re-uses the digest already on the
rows rather than re-resolving the plan's own environment -- re-resolving would
silently re-point a frozen run at whatever the plan points at today.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import iso8601_now, query_rows
from yoke_core.domain.qa_deployment_case_correction_window import (
    determinate_verdict,
)
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder, _plan_row
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    refresh_requirement,
)


#: Deployment stages materialize post-deploy obligations; the attachment
#: shape the snapshot writers expect carries only that phase.
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
            "superseded_by_requirement_id,execution_target_json,"
            "execution_target_digest FROM qa_requirements "
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
            f"({len(digests)} distinct targets); resolve it against the active "
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


def rematerialize_for_deployment_stage(
    conn: Any,
    *,
    deployment_run_id: str,
    deployment_stage: str,
    deployment_member_item_id: int | None = None,
    plan: str | int | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Refresh this subject's plan cases from their current plan definitions."""
    subject = (
        f"deployment run {str(deployment_run_id)!r} stage "
        f"{str(deployment_stage)!r} member {deployment_member_item_id!r}"
    )
    rows = _scoped_rows(
        conn,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    if not rows:
        raise QaPlanError(
            f"{subject} has no materialized plan cases to refresh; materialize "
            "the plan onto the stage first"
        )
    execution_target = _pinned_target(rows, subject=subject)

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

    answered: list[str] = []
    created: list[int] = []
    refreshed: list[int] = []
    for plan_id, plan_rows in rows_by_plan.items():
        plan_row = _plan_row(conn, plan_id)
        existing_ids = {
            (str(row["plan_case_key"]), row["host_baseline"]): int(row["id"])
            for row in plan_rows
        }
        cases = query_rows(
            conn,
            "SELECT c.*, m.name AS method_name, m.runner_id, "
            "m.required_capability_kinds, m.verdict_path, m.config_contract_id "
            f"FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
            f"WHERE c.plan_id={_placeholder(conn)} ORDER BY c.position",
            (plan_id,),
        )
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be rematerialized"
            )
        for case in cases:
            baselines = json.loads(str(case["host_baselines"] or "[]")) or [None]
            for baseline_position, baseline in enumerate(baselines, start=1):
                key = (str(case["case_key"]), baseline)
                requirement_id = existing_ids.get(key)
                if requirement_id is None:
                    inserted = insert_requirement(
                        conn,
                        deployment_run_id=str(deployment_run_id),
                        deployment_stage=str(deployment_stage),
                        deployment_member_item_id=deployment_member_item_id,
                        plan=plan_row,
                        attachment=_DEPLOYMENT_ATTACHMENT,
                        case=case,
                        baseline=baseline,
                        baseline_position=baseline_position,
                        now=iso8601_now(),
                        execution_target=execution_target,
                    )
                    if inserted is None:
                        inserted = existing_requirement_id(
                            conn,
                            deployment_run_id=str(deployment_run_id),
                            deployment_stage=str(deployment_stage),
                            deployment_member_item_id=deployment_member_item_id,
                            plan_id=plan_id,
                            case_key=key[0],
                            baseline=baseline,
                        )
                    if inserted is None:
                        raise QaPlanError(
                            f"{subject} could not materialize case {key[0]!r}"
                        )
                    created.append(int(inserted))
                    continue
                verdict = determinate_verdict(conn, requirement_id)
                if verdict:
                    answered.append(
                        f"requirement #{requirement_id} ({key[0]}) already recorded "
                        f"{verdict}"
                    )
                    continue
                refresh_requirement(
                    conn,
                    requirement_id=requirement_id,
                    transition_id=None,
                    plan=plan_row,
                    attachment=_DEPLOYMENT_ATTACHMENT,
                    case=case,
                    baseline=baseline,
                    baseline_position=baseline_position,
                    execution_target=execution_target,
                )
                refreshed.append(requirement_id)

    if answered:
        # Refused whole rather than partially applied: a caller correcting a
        # plan wants to know its stage is not uniformly refreshed, and half a
        # refresh is the state hardest to reason about afterwards.
        conn.rollback()
        raise QaPlanError(
            f"{subject} cannot be refreshed in place because "
            f"{len(answered)} case(s) have already answered: "
            f"{'; '.join(answered)}. An answered case is an acceptance record. "
            "Materialize the corrected case and record it with "
            "'yoke qa requirement supersede --requirement-id <answered-id> "
            "--superseded-by-requirement-id <corrected-id> --rationale \"<why>\"' "
            "once it has passed."
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
    }


__all__ = ["rematerialize_for_deployment_stage"]

"""Refresh QA plan requirements while retaining completed run history.

This is the one supported way to bring a live item requirement back to its
plan's current text, and it reaches every executable column — instructions and
expected_outcome included — because :func:`refresh_requirement` rewrites the
derivation whole rather than going through the narrow ``qa.requirement.update``
allowlist. What it will not touch is named by :mod:`qa_plan_refresh_safety`:
it refuses, before writing anything, when a live execution or an unreachable
admitted copy has already frozen a copy of the rows it would refresh.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import iso8601_now, query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_execution_environment_target import (
    resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_attachment_validation import (
    validate_attached_item_transition,
)
from yoke_core.domain.qa_deployment_member_attached_plans import (
    attachments_still_owed,
)
from yoke_core.domain.qa_plan_attachments import _attached_plans
from yoke_core.domain.qa_plan_execution_target_snapshot import (
    rebind_unresolvable_targets,
)
from yoke_core.domain.qa_plan_case_definition import case_baselines, plan_cases
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder, _plan_row
from yoke_core.domain.qa_plan_refresh_safety import (
    correct_admitted_copies,
    require_no_live_execution,
    require_reachable_admitted_copies,
)
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    refresh_requirement,
    require_existing_target,
    require_requirement_id_target,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


REPLACEMENT_RATIONALE = "Removed from the current QA plan definition."


@rollback_workflow_binding_write_errors
def rematerialize_for_item(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
    commit: bool = True,
) -> dict:
    """Refresh current plan snapshots and waive cases no longer in the plan."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    transition_id = str(transition_id or "").strip()
    attachments = attachments_still_owed(
        conn,
        member_item_id=int(item_id),
        attachments=_attached_plans(
            conn, item_id=int(item_id), transition_id=transition_id
        ),
    )[0]
    if not attachments:
        # Nothing live to refresh — a retracted attachment included. A
        # delivery that already answered is the same empty snapshot.
        return {
            "item_id": int(item_id),
            "transition_id": transition_id,
            "plan_ids": [],
            "created_requirement_ids": [],
            "refreshed_requirement_ids": [],
            "waived_requirement_ids": [],
        }
    transition_id = validate_attached_item_transition(
        conn,
        item_id=int(item_id),
        transition_id=transition_id,
        attachments=attachments,
    )
    marker = _placeholder(conn)
    rows = query_rows(
        conn,
        "SELECT id, plan_id, plan_case_key, host_baseline, waived_at, "
        "execution_target_json, execution_target_digest FROM qa_requirements "
        f"WHERE item_id={marker} AND workflow_transition_id={marker} "
        "AND plan_id IS NOT NULL ORDER BY id",
        (int(item_id), transition_id),
    )
    subject = f"{render_item_ref(conn, item_id)} transition {transition_id!r}"
    # Both refusals run before the first write: a refresh that stops halfway
    # leaves exactly the half-corrected state this operation exists to end.
    require_no_live_execution(
        conn, subject=subject, item_id=int(item_id), transition_id=transition_id
    )
    require_reachable_admitted_copies(conn, [int(row["id"]) for row in rows])
    rows_by_plan: dict[int, list[Any]] = {}
    for row in rows:
        rows_by_plan.setdefault(int(row["plan_id"]), []).append(row)
    created_requirement_ids: list[int] = []
    refreshed_requirement_ids: list[int] = []
    corrected_admitted_copy_ids: list[int] = []
    retained_requirement_ids: set[int] = set()
    now = iso8601_now()
    for plan_id, attachment in attachments.items():
        plan = _plan_row(conn, plan_id)
        execution_target = resolve_plan_execution_target(conn, plan_id=plan_id)
        # Before the strict reuse check, let go of any stored target the plan
        # no longer resolves to. Rematerializing is exactly the moment a moved
        # environment binding can be honored, because every retained row is
        # refreshed against the current target further down.
        plan_rows = rebind_unresolvable_targets(
            conn,
            rows_by_plan.get(plan_id, []),
            execution_target=execution_target,
        )
        require_existing_target(
            plan_rows,
            execution_target=execution_target,
            subject=subject,
        )
        existing_ids = {
            (str(row["plan_case_key"]), row["host_baseline"]): int(row["id"])
            for row in plan_rows
        }
        cases = plan_cases(conn, plan_id)
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be materialized"
            )
        for case in cases:
            for baseline_position, baseline in enumerate(
                case_baselines(case), start=1
            ):
                key = (str(case["case_key"]), baseline)
                requirement_id = existing_ids.get(key)
                if requirement_id is None:
                    requirement_id = insert_requirement(
                        conn,
                        item_id=int(item_id),
                        transition_id=transition_id,
                        plan=plan,
                        attachment=attachment,
                        case=case,
                        baseline=baseline,
                        baseline_position=baseline_position,
                        now=now,
                        execution_target=execution_target,
                    )
                    if requirement_id is not None:
                        created_requirement_ids.append(requirement_id)
                    else:
                        requirement_id = existing_requirement_id(
                            conn,
                            item_id=int(item_id),
                            plan_id=plan_id,
                            case_key=key[0],
                            baseline=baseline,
                            transition_id=transition_id,
                        )
                        if requirement_id is None:
                            raise QaPlanError("could not refresh QA plan requirement")
                        require_requirement_id_target(
                            conn,
                            requirement_id=requirement_id,
                            execution_target=execution_target,
                            subject=subject,
                        )
                else:
                    definition = refresh_requirement(
                        conn,
                        requirement_id=requirement_id,
                        transition_id=transition_id,
                        plan=plan,
                        attachment=attachment,
                        case=case,
                        baseline=baseline,
                        baseline_position=baseline_position,
                        execution_target=execution_target,
                    )
                    refreshed_requirement_ids.append(requirement_id)
                    corrected_admitted_copy_ids.extend(
                        correct_admitted_copies(
                            conn,
                            source_requirement_id=requirement_id,
                            definition=definition,
                        )
                    )
                retained_requirement_ids.add(requirement_id)
    waived_requirement_ids = [
        int(row["id"])
        for row in rows
        if row["waived_at"] is None and int(row["id"]) not in retained_requirement_ids
    ]
    for requirement_id in waived_requirement_ids:
        conn.execute(
            "UPDATE qa_requirements "
            f"SET waived_at={marker}, waiver_rationale={marker}, "
            f"waiver_source={marker} WHERE id={marker}",
            (iso8601_now(), REPLACEMENT_RATIONALE, "system", requirement_id),
        )
    if commit:
        conn.commit()
    return {
        "item_id": int(item_id),
        "transition_id": transition_id,
        "plan_ids": list(attachments),
        "created_requirement_ids": created_requirement_ids,
        "refreshed_requirement_ids": refreshed_requirement_ids,
        "corrected_admitted_copy_ids": sorted(set(corrected_admitted_copy_ids)),
        "waived_requirement_ids": waived_requirement_ids,
    }


__all__ = ["REPLACEMENT_RATIONALE", "rematerialize_for_item"]

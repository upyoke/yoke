"""Refresh QA plan requirements while retaining completed run history.

This is the one supported way to bring a live item requirement back to its
plan's current text, and it reaches every executable column — instructions and
expected_outcome included — because :func:`refresh_requirement` rewrites the
derivation whole rather than going through the narrow ``qa.requirement.update``
allowlist. What it will not touch is named by :mod:`qa_plan_refresh_safety`:
a case a live walk already reached, and an admitted copy that can no longer
take the change. A case a live walk has not reached takes the correction.

One call converges the transition on its plans: a case added since the last
materialization gets its row, an amended case's row is refreshed, and a row
whose case left the plan is retired. A plan a delivery has already answered
still has its existing rows refreshed and retired, but gains no new row -- a
fresh obligation there could only be answered by a run that already finished.

Retiring a ``post_deploy`` row whose case was replaced records the replacement
rather than waiving it: when exactly one row this call created answers the
same obligation (same item, transition, phase, environment and baseline), the
old row is superseded by it. The corrected row is then the obligation, and a
run that already admitted the old case answers it through those copies
(:func:`~yoke_core.domain.qa_requirement_source_retirement.admitted_source_lineage`).
A waiver would claim nobody needs the proof; the supersession says which row
now carries it. A row with no single successor -- its case was dropped, or
several new cases could each claim it -- is waived as removed.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, utc_now, query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_case_targets import case_variants
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
from yoke_core.domain.qa_plan_case_definition import (
    case_baselines,
    materialized_definition,
    plan_cases,
)
from yoke_core.domain.qa_obligation_settlement import obligation_settled
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder, _plan_row
from yoke_core.domain.qa_admitted_copy_correction import (
    correct_admitted_copies,
    lock_admitted_copies,
)
from yoke_core.domain.qa_plan_refresh_safety import carry_into_live_rosters
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
SUCCESSOR_RATIONALE = (
    "Replaced in the current QA plan definition by requirement {successor_id}; "
    "it carries this post_deploy obligation."
)


@rollback_workflow_binding_write_errors
def rematerialize_for_item(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
    commit: bool = True,
) -> dict:
    """Refresh current plan snapshots and retire cases no longer in the plan."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    transition_id = str(transition_id or "").strip()
    attached = _attached_plans(conn, item_id=int(item_id), transition_id=transition_id)
    if attached:
        transition_id = validate_attached_item_transition(
            conn,
            item_id=int(item_id),
            transition_id=transition_id,
            attachments=attached,
        )
    marker = _placeholder(conn)
    rows = query_rows(
        conn,
        "SELECT * FROM qa_requirements "
        f"WHERE item_id={marker} AND workflow_transition_id={marker} "
        "AND plan_id IS NOT NULL ORDER BY id",
        (int(item_id), transition_id),
    )
    # A plan a delivery already answered owes no fresh row, but the rows it
    # already has still stand for it and must still come current: skipping
    # them left a stale row nothing could refresh.
    owed = attachments_still_owed(
        conn, member_item_id=int(item_id), attachments=attached
    )[0]
    materialized_plan_ids = {int(row["plan_id"]) for row in rows}
    attachments = {
        plan_id: attachment
        for plan_id, attachment in attached.items()
        if plan_id in owed or plan_id in materialized_plan_ids
    }
    if not attachments:
        # Nothing attached, or nothing a delivery has not already answered
        # and nothing materialized from it: an empty snapshot is the truth.
        return {
            "item_id": int(item_id),
            "transition_id": transition_id,
            "plan_ids": [],
            "created_requirement_ids": [],
            "refreshed_requirement_ids": [],
            "superseded_requirement_ids": {},
            "waived_requirement_ids": [],
        }
    subject = f"{render_item_ref(conn, item_id)} transition {transition_id!r}"
    projections = lock_admitted_copies(conn, [int(row["id"]) for row in rows])
    rows_by_plan: dict[int, list[Any]] = {}
    for row in rows:
        rows_by_plan.setdefault(int(row["plan_id"]), []).append(row)
    created_requirement_ids: list[int] = []
    refreshed_requirement_ids: list[int] = []
    corrected_admitted_copy_ids: list[int] = []
    retained_requirement_ids: set[int] = set()
    now = utc_now()
    for plan_id, attachment in attachments.items():
        plan = _plan_row(conn, plan_id)
        cases = plan_cases(conn, plan_id)
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be materialized"
            )
        variants = case_variants(conn, plan=plan, cases=cases)
        for case, target_env, execution_target in variants:
            plan_rows = [
                row
                for row in rows_by_plan.get(plan_id, [])
                if (row["target_env"] or None) == target_env
                and row["plan_case_key"] == case["case_key"]
            ]
            plan_rows = rebind_unresolvable_targets(
                conn, plan_rows, execution_target=execution_target
            )
            require_existing_target(
                plan_rows, execution_target=execution_target, subject=subject, conn=conn
            )
            existing_ids = {
                (str(row["plan_case_key"]), row["host_baseline"]): int(row["id"])
                for row in plan_rows
            }
            for baseline_position, baseline in enumerate(case_baselines(case), start=1):
                key = (str(case["case_key"]), baseline)
                requirement_id = existing_ids.get(key)
                if requirement_id is None and plan_id not in owed:
                    continue
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
                        target_env=target_env,
                    )
                    if requirement_id is not None:
                        created_requirement_ids.append(requirement_id)
                        # A run may already hold a copy answering this plan
                        # case; it needs the body just written, as a
                        # refreshed row's copies do.
                        corrected_admitted_copy_ids.extend(
                            correct_admitted_copies(
                                conn,
                                source_requirement_id=requirement_id,
                                projections=projections,
                                definition=materialized_definition(
                                    plan=plan,
                                    case=case,
                                    qa_phase=str(attachment["qa_phase"]),
                                    baseline=baseline,
                                    baseline_position=baseline_position,
                                    transition_id=transition_id,
                                    execution_target=execution_target,
                                    target_env=target_env,
                                ),
                            )
                        )
                    else:
                        requirement_id = existing_requirement_id(
                            conn,
                            item_id=int(item_id),
                            plan_id=plan_id,
                            case_key=key[0],
                            baseline=baseline,
                            transition_id=transition_id,
                            target_env=target_env,
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
                        target_env=target_env,
                    )
                    refreshed_requirement_ids.append(requirement_id)
                    corrected_admitted_copy_ids.extend(
                        correct_admitted_copies(
                            conn,
                            source_requirement_id=requirement_id,
                            definition=definition,
                            projections=projections,
                        )
                    )
                retained_requirement_ids.add(requirement_id)
    retired = [
        dict(row)
        for row in rows
        if not obligation_settled(row)
        and int(row["id"]) not in retained_requirement_ids
    ]
    superseded = _supersede_replaced(conn, retired, created_requirement_ids)
    waived_requirement_ids = [
        int(row["id"]) for row in retired if int(row["id"]) not in superseded
    ]
    for requirement_id in waived_requirement_ids:
        conn.execute(
            "UPDATE qa_requirements "
            f"SET waived_at={marker}, waiver_rationale={marker}, "
            f"waiver_source={marker} WHERE id={marker}",
            (
                instant_parameter(conn, utc_now()),
                REPLACEMENT_RATIONALE,
                "system",
                requirement_id,
            ),
        )
    # A refusal here raises inside this transaction, so the rollback leaves
    # every row and roster as it was; a passed case is never replayed.
    carry_into_live_rosters(
        conn,
        subject=subject,
        rewritten=[*refreshed_requirement_ids, *superseded, *waived_requirement_ids],
        created=created_requirement_ids,
        item_id=int(item_id),
        transition_id=transition_id,
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
        "superseded_requirement_ids": superseded,
        "waived_requirement_ids": waived_requirement_ids,
    }


def _supersede_replaced(
    conn: Any, retired: list[dict[str, Any]], created_ids: list[int]
) -> dict[int, int]:
    """Supersede each retired post_deploy row by its one created successor."""
    from yoke_core.domain.qa_replacement_scope_guard import link_mismatches

    if not created_ids:
        return {}
    marker = _placeholder(conn)
    created = [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT * FROM qa_requirements WHERE id IN "
            f"({','.join(marker for _ in created_ids)}) ORDER BY id",
            tuple(created_ids),
        )
    ]
    superseded: dict[int, int] = {}
    for row in retired:
        if str(row.get("qa_phase") or "") != "post_deploy":
            continue
        successors = [
            new
            for new in created
            if new["plan_id"] == row["plan_id"] and not link_mismatches(row, new)
        ]
        if len(successors) != 1:
            continue
        successor_id = int(successors[0]["id"])
        conn.execute(
            "UPDATE qa_requirements SET superseded_by_requirement_id="
            f"{marker}, superseded_at={marker}, supersession_rationale={marker}, "
            f"supersession_source={marker} WHERE id={marker}",
            (
                successor_id,
                instant_parameter(conn, utc_now()),
                SUCCESSOR_RATIONALE.format(successor_id=successor_id),
                "system",
                int(row["id"]),
            ),
        )
        superseded[int(row["id"])] = successor_id
    return superseded


__all__ = ["REPLACEMENT_RATIONALE", "SUCCESSOR_RATIONALE", "rematerialize_for_item"]

"""Judge a run's composition before the run lock, against proposed members.

Adding a member row locks its run row through the foreign key, so
:func:`judge_composition` reads the existing members plus the rows an
enrollment would add, and every check runs before any of them exist.
"""

from __future__ import annotations

from typing import Any, List, Tuple

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_member_post_deploy_admission import (
    unadmitted_post_deploy_notice,
)
from yoke_core.domain.deployment_member_run_coverage import (
    inert_membership_notice,
    unclosable_final_member_refusal,
)
from yoke_core.domain.deployment_run_carried_membership import (
    apply_carried_enrollment,
    describe_enrollment,
)
from yoke_core.domain.deployment_run_carried_membership_refusal import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_composition_guard import has_frozen_composition
from yoke_core.domain.deployment_run_enrollment_error import CarriedEnrollmentError
from yoke_core.domain.deployment_run_item_qa_membership import (
    item_qa_membership_verdict,
)
from yoke_core.domain.deployment_run_pair_obligations import (
    split_pending_pair_merges,
)
from yoke_core.domain.deployment_run_project_sources import carried_project_ids
from yoke_core.domain.deployment_run_proposed_membership import (
    proposed_membership,
    run_items,
)
from yoke_core.domain.deployment_run_reopened_members import (
    frozen_member_readiness,
)
from yoke_core.domain.deployment_run_skipped_candidates import skipped_candidate_notice
from yoke_core.domain.deployment_runs_validation import (
    _item_label,
    _not_delivery_ready,
)
from yoke_core.domain.project_identity import (
    render_item_ref,
    resolve_project_slug,
)


def judge_composition(
    conn: Any,
    run_id: str,
    run_project_id: int,
    *,
    errors: List[str],
    enrolled: tuple[str, ...],
    carried: Any,
    custody: Any,
    enrollment_error: Any,
    allow_pending_pair_merges: bool,
    composition_result: dict[str, Any] | None,
    require_item_qa_members: bool,
) -> Tuple[bool, str]:
    """Every check after enrollment; membership is read through ``run_items``.

    Inside ``proposed_membership`` it judges rows not inserted yet, which is
    how a caller judges a composition before taking the run row lock.
    """
    errors = list(errors)
    run_project_id = int(run_project_id)
    run_project = resolve_project_slug(conn, run_project_id)

    # Check 1: every item belongs to a project this run ships source for
    carried_projects = carried_project_ids(conn, run_id)
    placeholders = ", ".join("%s" for _ in carried_projects)
    wrong_project = query_rows(
        conn,
        "SELECT i.id, p.slug "
        f"FROM {run_items('dri')} "
        "JOIN items i ON dri.item_id = i.id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE dri.run_id=%s AND i.project_id NOT IN ({placeholders})",
        (run_id, *carried_projects),
    )
    if wrong_project:
        items_str = ", ".join(
            _item_label(conn, row[0], f"project={row[1]}") for row in wrong_project
        )
        carried_labels = ", ".join(
            resolve_project_slug(conn, project_id) for project_id in carried_projects
        )
        errors.append(
            f"Project mismatch (run {run_project} ships source for "
            f"{carried_labels}): {items_str}"
        )

    # Check 2: Every item is delivery-ready for its pinned workflow.
    # A frozen run already deployed its members' landed code; one that
    # reopened since is set aside or refused by name, never re-admitted.
    set_aside = ""
    if has_frozen_composition(conn, run_id):
        not_passed, set_aside = frozen_member_readiness(conn, run_id)
        delivery_candidates = query_rows(
            conn,
            f"SELECT item_id, '' FROM {run_items()} WHERE run_id=%s",
            (run_id,),
        )
    else:
        delivery_candidates = query_rows(
            conn,
            f"SELECT i.id, i.status FROM {run_items('dri')} "
            "JOIN items i ON dri.item_id = i.id WHERE dri.run_id=%s",
            (run_id,),
        )
        not_passed = _not_delivery_ready(
            conn, delivery_candidates, allow_completed=True
        )
    if not_passed:
        errors.append(
            "Items not delivery-ready for their pinned workflow: "
            + ", ".join(not_passed)
        )

    # Check 3: Unsatisfied hard-block dependencies
    member_item_ids = [int(row[0]) for row in delivery_candidates]
    pending_pairs, blocked = split_pending_pair_merges(conn, member_item_ids)
    if pending_pairs and not allow_pending_pair_merges:
        blocked = [
            (pair.dependent_item_id, pair.blocking_item_id, pair)
            for pair in pending_pairs
        ] + blocked
    if blocked:
        items_str = ", ".join(
            f"{render_item_ref(conn, int(dependent))} (blocked by "
            f"{render_item_ref(conn, int(blocker))}: {verdict.reason})"
            for dependent, blocker, verdict in blocked
        )
        errors.append(f"Unsatisfied hard-block dependencies: {items_str}")

    if composition_result is not None:
        composition_result["enrolled"] = enrolled
    carried_refusal = carried_membership_refusal(
        conn,
        run_id,
        carried_work=carried,
        custody=custody,
        enrollment_error=enrollment_error,
    )
    if carried_refusal:
        errors.append(carried_refusal)

    if unclosable := unclosable_final_member_refusal(conn, run_id, custody=custody):
        errors.append(unclosable)
    item_qa, no_member = item_qa_membership_verdict(
        conn, run_id, require_members=require_item_qa_members
    )
    errors.extend([item_qa] if item_qa else [])
    unadmitted = unadmitted_post_deploy_notice(conn, run_id)
    inert = inert_membership_notice(conn, run_id)
    held = skipped_candidate_notice(conn, run_id, custody=custody, carried_work=carried)

    if errors:
        trailing = [note for note in (set_aside, held, inert, unadmitted) if note]
        error_text = "\n".join(errors + trailing)
        return False, f"FAIL: Composition validation failed:\n{error_text}"

    notes = [
        note
        for note in (
            describe_enrollment(enrolled),
            set_aside,
            held,
            inert,
            unadmitted,
            no_member,
        )
        if note
    ]
    return True, ("OK; " + "; ".join(notes)) if notes else "OK"


def judge_then_enroll(conn, run_id, enrollment, errors, judge) -> Tuple[bool, str]:
    """Judge the enrolled composition before the run lock, then enroll under it.

    The judgement reads the rows enrollment would insert as members, so it
    runs before the run row lock; enrollment then takes the lock, confirms
    its decision with a constant re-check and inserts. A decision that did
    not go as planned is judged again in place, holding the lock.
    """
    if enrollment.refusal is not None:
        planned = (
            [*errors, str(enrollment.refusal)],
            (),
            enrollment.refusal
            if isinstance(enrollment.refusal, CarriedEnrollmentError)
            else None,
        )
    else:
        planned = (errors, enrollment.refs, None)
    with proposed_membership(conn, run_id, enrollment.proposed_rows):
        verdict = judge(
            errors=planned[0], enrolled=planned[1], enrollment_error=planned[2]
        )
    outcome = apply_carried_enrollment(conn, run_id, enrollment)
    if outcome.as_planned:
        return verdict
    found = [*errors, str(outcome.error)] if outcome.error is not None else errors
    return judge(
        errors=found,
        enrolled=outcome.refs,
        enrollment_error=outcome.error
        if isinstance(outcome.error, CarriedEnrollmentError)
        else None,
    )


__all__ = ["judge_composition", "judge_then_enroll"]

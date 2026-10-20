"""Composition and batch-compatibility validation for deployment runs.

Owns: ``cmd_validate_composition`` (provisional and explicit membership check) and
``cmd_check_batch_compatibility`` (pre-creation batch check, in
:mod:`deployment_runs_batch_compatibility`). Both enforce
project alignment, item-status floor, and hard-block dependency detection. Selected flow is completion
authority: a final-delivery release refuses a member it could not close.
"""

from __future__ import annotations

from functools import partial
from typing import Any, List, Optional, Tuple

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.deployment_member_post_deploy_admission import (
    unadmitted_post_deploy_notice,
)
from yoke_core.domain.deployment_member_run_coverage import (
    inert_membership_notice,
    unclosable_final_member_refusal,
)
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_membership import (
    apply_carried_enrollment,
    carried_enrollment_blocked,
    describe_enrollment,
    enroll_carried_members,
    plan_carried_enrollment,
)
from yoke_core.domain.deployment_run_carried_membership_refusal import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_carried_work import carried_work_for_enrollment
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
from yoke_core.domain.deployment_run_unheld_candidates import (
    CustodyResolution,
    resolve_candidate_custody,
)
from yoke_core.domain.deployment_runs_batch_compatibility import (
    _item_label,
    _not_delivery_ready,
)
from yoke_core.domain.deployment_source_reads import SourcePreparationChanged
from yoke_core.domain.project_identity import (
    render_item_ref,
    resolve_project_slug,
)
from yoke_core.domain.schema_read_scope import composition_operation


@composition_operation
def cmd_validate_composition(
    run_id: str,
    db_path: Optional[str] = None,
    *,
    allow_pending_pair_merges: bool = False,
    connection: Any = None,
    composition_result: dict[str, Any] | None = None,
    require_item_qa_members: bool = True,
    custody: CustodyResolution | None = None,
) -> Tuple[bool, str]:
    """Validate run composition. Returns (ok, message).

    Checks:
    1. All items share the run's project
    2. Every item is delivery-ready under its pinned workflow policy
    3. No unsatisfied hard-block dependencies outside the run
    4. Item-scoped QA has custody, and a memberless run owes no delivery

    ``allow_pending_pair_merges`` is what preparation passes: a run prepared
    before its coordinated pair has landed is expected to carry unsatisfied
    pair-merge edges; only those, and only then — continuation re-runs this
    with the default and so proves the pair actually merged.
    """
    # Run creation checks its provisional row before committing it. The
    # explicit command owns a connection and persists the source bindings and
    # enrollment it resolved, as it did before this transactional entry point.
    conn = connection if connection is not None else connect(db_path)
    try:
        run_project_id = query_scalar(
            conn, "SELECT project_id FROM deployment_runs WHERE id=%s", (run_id,)
        )
        if run_project_id is None:
            return False, f"FAIL: Run '{run_id}' not found"
        # Completing membership before the checks below is what lets the same
        # checks judge the run that will actually execute. Enrolling after
        # them would validate a composition the start no longer has.
        errors: List[str] = []
        enrolled: tuple[str, ...] = ()
        # Unresolved until the bound sources it reads are recorded. A reader
        # handed None walks custody itself, which is the honest fallback when
        # recording those sources is the thing that failed.
        carried = None
        enrollment_error = None
        enrollment = None
        try:
            # The run's source commit per project is resolved and recorded
            # before anything reads it, so enrollment and every check below
            # judge the commits this run will actually ship.
            record_bound_sources(conn, run_id)
            # Custody walks GitHub containment once per carried project, and
            # every reader below needs the same answer. Resolving it here --
            # after the bound sources it reads, before enrollment takes the run
            # row -- is what keeps the network out of that lock: asking each
            # reader to walk for itself put three round trips inside it, and a
            # client that hibernated mid-walk pinned the row until a human
            # terminated its backend. Custody excludes this run, so enrolling
            # its own members cannot invalidate the answer.
            custody = custody or resolve_candidate_custody(conn, run_id)
            # Derived once: enrollment and the skipped notice read one answer.
            if not carried_enrollment_blocked(conn, run_id):
                carried = carried_work_for_enrollment(conn, run_id)
                enrollment = plan_carried_enrollment(
                    conn, run_id, carried_work=carried, custody=custody
                )
            if enrollment is not None and enrollment.basis is None:
                # This schema cannot prove an unlocked judgement current, so
                # the rows go in first and the checks judge them in place.
                unproven, enrollment = enrollment, None
                enrolled = enroll_carried_members(conn, run_id, enrollment=unproven)
        except SourcePreparationChanged:
            raise
        except (LookupError, ValueError) as exc:
            errors.append(str(exc))
            if isinstance(exc, CarriedEnrollmentError):
                enrollment_error = exc
        judge = partial(
            judge_composition,
            conn,
            run_id,
            int(run_project_id),
            carried=carried,
            custody=custody,
            allow_pending_pair_merges=allow_pending_pair_merges,
            composition_result=composition_result,
            require_item_qa_members=require_item_qa_members,
        )
        if enrollment is None or not enrollment.candidates:
            verdict = judge(
                errors=errors, enrolled=enrolled, enrollment_error=enrollment_error
            )
        else:
            verdict = judge_then_enroll(conn, run_id, enrollment, errors, judge)
        if connection is None:
            (conn.commit if verdict[0] else conn.rollback)()
        return verdict
    finally:
        if connection is None:
            conn.close()


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


__all__ = [
    "judge_composition",
    "cmd_validate_composition",
]

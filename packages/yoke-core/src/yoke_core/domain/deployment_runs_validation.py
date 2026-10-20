"""Composition and batch-compatibility validation for deployment runs.

Owns: ``cmd_validate_composition`` (provisional and explicit membership check) and
``cmd_check_batch_compatibility`` (pre-creation batch check). Both enforce
project alignment, item-status floor, and hard-block dependency detection. Selected flow is completion
authority: a final-delivery release refuses a member it could not close.
"""

from __future__ import annotations

from functools import partial
from typing import Any, List, Optional, Sequence, Tuple

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.dependency_satisfaction import unsatisfied_dependency_pairs
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_membership import (
    carried_enrollment_blocked,
    enroll_carried_members,
    plan_carried_enrollment,
)
from yoke_core.domain.deployment_run_carried_work import carried_work_for_enrollment
from yoke_core.domain.deployment_run_enrollment_error import CarriedEnrollmentError
from yoke_core.domain.deployment_run_reopened_members import (
    unready_item_ids,
)
from yoke_core.domain.deployment_run_unheld_candidates import (
    CustodyResolution,
    resolve_candidate_custody,
)
from yoke_core.domain.deployment_source_reads import SourcePreparationChanged
from yoke_core.domain.project_identity import (
    render_item_ref,
    resolve_project,
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
        from yoke_core.domain.deployment_runs_composition_judgement import (
            judge_then_enroll,
            judge_composition,
        )

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


def _item_label(conn, item_id: int, detail: str) -> str:
    """Name one item in a refusal listing.

    Not strict: this builds the list of items blocking a run, so an entry
    whose identity will not resolve says so and the operator still sees
    every other blocker. Raising here would replace the whole answer with
    one lookup failure.
    """
    return f"{render_item_ref(conn, int(item_id))} ({detail})"


def _not_delivery_ready(conn, rows, *, allow_completed: bool = False) -> list[str]:
    status_of = {int(item_id): status for item_id, status in rows}
    return [
        _item_label(conn, item_id, f"status={status_of[item_id]}")
        for item_id in unready_item_ids(conn, rows, allow_completed=allow_completed)
    ]


def cmd_check_batch_compatibility(
    project: str,
    flow: str,
    item_ids: Sequence[int],
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Validate proposed items before run creation. Returns (ok, message).

    Same checks as validate-composition but against a proposed batch of items.
    """
    if not item_ids:
        return False, "FAIL: No item IDs provided"

    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project)
        assert ident is not None
        _ = flow
        placeholders = ",".join("%s" for _ in item_ids)
        errors: List[str] = []

        wrong_project = query_rows(
            conn,
            f"SELECT i.id, p.slug "
            f"FROM items i "
            f"JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({placeholders}) AND i.project_id <> %s",
            tuple(item_ids) + (ident.id,),
        )
        if wrong_project:
            items_str = ", ".join(
                _item_label(conn, row[0], f"project={row[1]}") for row in wrong_project
            )
            errors.append(f"Project mismatch (batch expects {ident.slug}): {items_str}")

        delivery_candidates = query_rows(
            conn,
            f"SELECT i.id, i.status FROM items i WHERE i.id IN ({placeholders})",
            tuple(item_ids),
        )
        not_passed = _not_delivery_ready(conn, delivery_candidates)
        if not_passed:
            errors.append(
                "Items not delivery-ready for their pinned workflow: "
                + ", ".join(not_passed)
            )

        blocked = unsatisfied_dependency_pairs(
            conn,
            item_ids,
            co_scheduled_blocker_ids=item_ids,
        )
        if blocked:
            items_str = ", ".join(
                f"{render_item_ref(conn, int(dependent))} (blocked by "
                f"{render_item_ref(conn, int(blocker))}: {verdict.reason})"
                for dependent, blocker, verdict in blocked
            )
            errors.append(f"Unsatisfied hard-block dependencies: {items_str}")

        if errors:
            error_text = "\n".join(errors)
            return False, f"FAIL: Batch compatibility check failed:\n{error_text}"

        return True, "OK"
    finally:
        conn.close()


__all__ = [
    "cmd_check_batch_compatibility",
    "cmd_validate_composition",
]

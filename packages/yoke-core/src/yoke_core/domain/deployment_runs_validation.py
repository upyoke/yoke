"""Composition and batch-compatibility validation for deployment runs.

Owns: ``cmd_validate_composition`` (post-creation membership check) and
``cmd_check_batch_compatibility`` (pre-creation batch check). Both enforce
project alignment, item-status floor, and
unsatisfied hard-block dependency detection. Selected flow is completion
authority: a final-delivery release refuses a member it could not close.
SQL bodies preserved verbatim
from the pre-split state-machine — no reordering, no early-return refactor.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.dependency_satisfaction import unsatisfied_dependency_pairs
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_project_sources import carried_project_ids
from yoke_core.domain.deployment_member_post_deploy_admission import (
    unadmitted_post_deploy_notice,
)
from yoke_core.domain.deployment_member_run_coverage import (
    inert_membership_notice,
    unclosable_final_member_refusal,
)
from yoke_core.domain.deployment_run_carried_membership import (
    carried_membership_refusal,
    describe_enrollment,
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_pair_obligations import (
    split_pending_pair_merges,
)
from yoke_core.domain.project_identity import (
    render_item_ref,
    resolve_project,
    resolve_project_slug,
)
from yoke_core.domain.schema_common import (
    _get_columns as _schema_get_columns,
    _table_exists,
)
from yoke_core.domain.workflow_delivery_binding_validation import (
    COMPLETED_ITEM_STAGE_ID,
    delivery_ready_for_stage,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    load_item_workflow_runtime,
)

_LEGACY_DELIVERY_READY_STAGES = frozenset({"implemented", "release", "done"})


def _item_label(conn, item_id: int, detail: str) -> str:
    """Name one item in a refusal listing.

    Not strict: this builds the list of items blocking a run, so an entry
    whose identity will not resolve says so and the operator still sees
    every other blocker. Raising here would replace the whole answer with
    one lookup failure.
    """
    return f"{render_item_ref(conn, int(item_id))} ({detail})"


def _not_delivery_ready(conn, rows, *, allow_completed: bool = False) -> list[str]:
    refused: list[str] = []
    item_columns = set(_schema_get_columns(conn, "items"))
    has_workflow_pins = (
        _table_exists(conn, "workflow_versions")
        and {
            "workflow_id",
            "workflow_version_id",
        }
        <= item_columns
    )
    for item_id, status in rows:
        if has_workflow_pins:
            runtime = load_item_workflow_runtime(conn, int(item_id))
            status_text = str(status)
            if status_text in runtime.terminal_stage_ids or (
                status_text in ENGINE_TERMINAL_STAGE_IDS
            ):
                ready = (
                    allow_completed
                    and status_text == COMPLETED_ITEM_STAGE_ID
                    and status_text in runtime.terminal_stage_ids
                )
            else:
                ready = delivery_ready_for_stage(runtime, status_text)
        else:
            ready = str(status) in _LEGACY_DELIVERY_READY_STAGES
        if not ready:
            refused.append(_item_label(conn, item_id, f"status={status}"))
    return refused


def cmd_validate_composition(
    run_id: str,
    db_path: Optional[str] = None,
    *,
    allow_pending_pair_merges: bool = False,
) -> Tuple[bool, str]:
    """Validate run composition. Returns (ok, message).

    Checks:
    1. All items share the run's project
    2. Every item is delivery-ready under its pinned workflow policy
    3. No unsatisfied hard-block dependencies outside the run

    ``allow_pending_pair_merges`` is what preparation passes: a run prepared
    before its coordinated pair has landed is expected to carry unsatisfied
    pair-merge edges, and remembering them is the whole point of preparing it.
    Only those edges are tolerated, and only at that phase — continuation
    re-runs this with the default and so proves the pair actually merged.
    """
    conn = connect(db_path)
    try:
        run_project_id = query_scalar(
            conn, "SELECT project_id FROM deployment_runs WHERE id=%s", (run_id,)
        )
        if run_project_id is None:
            return False, f"FAIL: Run '{run_id}' not found"
        # Completing membership before the checks below is what lets the same
        # checks judge the run that will actually execute. Enrolling after
        # them would validate a composition the start no longer has.
        try:
            # The run's source commit per project is resolved and recorded
            # before anything reads it, so enrollment and every check below
            # judge the commits this run will actually ship.
            record_bound_sources(conn, run_id)
            enrolled = enroll_carried_members(conn, run_id)
            conn.commit()
        except (LookupError, ValueError) as exc:
            conn.rollback()
            return False, f"FAIL: Composition validation failed:\n{exc}"
        run_project_id = int(run_project_id)
        run_project = resolve_project_slug(conn, run_project_id)

        errors: List[str] = []

        # Check 1: every item belongs to a project this run ships source for
        carried_projects = carried_project_ids(conn, run_id)
        placeholders = ", ".join("%s" for _ in carried_projects)
        wrong_project = query_rows(
            conn,
            "SELECT i.id, p.slug "
            "FROM deployment_run_items dri "
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
                resolve_project_slug(conn, project_id)
                for project_id in carried_projects
            )
            errors.append(
                f"Project mismatch (run {run_project} ships source for "
                f"{carried_labels}): {items_str}"
            )

        # Check 2: Every item is delivery-ready for its pinned workflow.
        delivery_candidates = query_rows(
            conn,
            "SELECT i.id, i.status "
            "FROM deployment_run_items dri "
            "JOIN items i ON dri.item_id = i.id "
            "WHERE dri.run_id=%s",
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
        run_items = [int(row[0]) for row in delivery_candidates]
        pending_pairs, blocked = split_pending_pair_merges(conn, run_items)
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

        carried_refusal = carried_membership_refusal(conn, run_id)
        if carried_refusal:
            errors.append(carried_refusal)

        # A release that would turn green over a final member it cannot
        # close strands that member at its release wait, so it never starts.
        if unclosable := unclosable_final_member_refusal(conn, run_id):
            errors.append(unclosable)

        # An obligation no stage on this run targets is not a composition
        # error -- a stage run legitimately carries an item whose prod
        # acceptance belongs to the production run -- but it is never
        # silent either, because it is exactly what will block that item's
        # done transition once this run succeeds.
        unadmitted = unadmitted_post_deploy_notice(conn, run_id)

        # Only the members this run can neither check nor close: one it can
        # close is the ordinary case, and restating that per member would
        # bury the membership that will receive nothing.
        inert = inert_membership_notice(conn, run_id)

        if errors:
            trailing = [note for note in (inert, unadmitted) if note]
            error_text = "\n".join(errors + trailing)
            return False, f"FAIL: Composition validation failed:\n{error_text}"

        notes = [
            note
            for note in (describe_enrollment(enrolled), inert, unadmitted)
            if note
        ]
        return True, ("OK; " + "; ".join(notes)) if notes else "OK"
    finally:
        conn.close()


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
        # ``flow`` identifies the proposed run. Whether that run may close each
        # final member is judged on its composition, before it executes.
        _ = flow
        # Build placeholders for IN clause
        placeholders = ",".join("%s" for _ in item_ids)
        errors: List[str] = []

        # Check 1: All items share the target project
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

        # Check 2: Every item is delivery-ready for its pinned workflow.
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

        # Check 3: Unsatisfied hard-block deps outside batch
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

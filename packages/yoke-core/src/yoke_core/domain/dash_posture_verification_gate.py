"""Whether a Dash item's selected verification posture is satisfied here.

Split out of :mod:`dash_posture_gate` to stay under the authored file line
budget. The posture gate owns which facts apply at which boundary; this owns
the one reading that answers for the selected verification case — that its
blocking QA requirements have a passing run at this transition, and which of
them a later completion run has already consumed.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.dash_posture_read import failure as _failure, marker as _p
from yoke_core.domain.deployment_qa_source_obligation import (
    POST_DEPLOY_RECOVERY,
    blocking_row_unsatisfied_at_done,
    source_obligation_consumed,
)
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.qa_obligation_settlement import (
    effective_requirement,
    obligation_settled,
)
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_requirement_replacement import replacement_note
from yoke_core.domain.qa_requirement_source_retirement import is_source_retirement
from yoke_core.domain.qa_review_requests import requirement_awaits_human_review
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)
from yoke_core.domain.schema_common import _table_exists


def _requirement_consumed(
    conn: Any,
    row: Any,
    *,
    pre_merge: bool,
    item_id: int,
    candidate_shas: tuple[str, ...],
) -> bool:
    """Whether this blocking row is satisfied at the boundary being crossed.

    Shared settlement discharges history; a superseding case still needs its
    own current, same-scope pass. A retired ``post_deploy`` source never
    runs, so its corrected item requirement answers through the source
    obligation instead. At done the source-obligation reading is
    asked even for a row that has passed: a ``post_deploy`` pass proves the candidate
    that was deployed when it ran, not the one being closed out.
    """
    passed = bool(row["passed"] if hasattr(row, "keys") else row[2])
    from yoke_core.domain.qa_latest_execution import latest_executions
    from yoke_core.domain.qa_simulation_triage import current_simulation_triage

    if obligation_settled(row):
        if (
            row.get("waived_at")
            or row.get("retracted_at")
            or row.get("triage_discharge")
        ):
            return True
        if is_source_retirement(row):
            replacement_id = int(
                row.get("replacement_requirement_id")
                or row.get("superseded_by_requirement_id")
                or 0
            )
            return not pre_merge and source_obligation_consumed(
                conn, item_id=int(item_id), source_requirement_id=replacement_id
            )
        try:
            row = effective_requirement(conn, int(row["id"]))
        except ValueError as exc:
            if not str(exc).startswith("replacement_graph_invalid:"):
                raise
            row["settlement_error"] = str(exc)
            return False
        row["triage_discharge"] = (
            current_simulation_triage(conn, int(row["id"]))
            if row.get("qa_kind") == "simulation"
            else None
        )
        if obligation_settled(row):
            return True
        row["passed"] = passed = has_current_passing_run(conn, int(row["id"]))
        from yoke_core.domain.qa_subject_proof import requires_code_identity

        if candidate_shas and requires_code_identity(row):
            latest = latest_executions(conn, [int(row["id"])]).get(int(row["id"]))
            if (
                not latest
                or recorded_head_sha(latest["raw_result"]) not in candidate_shas
            ):
                return False
    if pre_merge:
        return passed
    phase = str(row["qa_phase"] if hasattr(row, "keys") else row[1] or "")
    source_id = int(row["id"] if hasattr(row, "keys") else row[0])
    return not blocking_row_unsatisfied_at_done(
        conn,
        item_id=int(item_id),
        source_requirement_id=source_id,
        qa_phase=phase,
        original_passed=passed,
    )


def verification_gate(
    conn: Any,
    *,
    item_id: int,
    verification: Mapping[str, Any],
    target_status: str,
    candidate_shas: tuple[str, ...] = (),
) -> Optional[dict[str, Any]]:
    if not all(
        _table_exists(conn, table)
        for table in (
            "qa_requirements",
            "qa_runs",
        )
    ):
        return _failure(
            "GATE_DASH_VERIFICATION_REQUIRED",
            "Selected Dash verification has no QA authority tables.",
            "Initialize QA, author the selected case, and record its run.",
        )
    marker = _p(conn)
    kind = str(verification.get("kind") or "")
    selector = "r.plan_id = " + marker
    selector_value: Any = verification.get("plan_id")
    if kind == "ad_hoc":
        selector = "r.plan_id IS NULL AND r.method_id = " + marker
        selector_value = str(verification.get("method_id") or "")
    # Pre-merge waits for verification only. At done, post_deploy is
    # consumed by this source's admitted copy on the completion run, not
    # a second original run or any historical copy. manual_acceptance
    # keeps its phase gate.
    pre_merge = target_status == ITEM_POSTURE_VERIFICATION_TRANSITION
    phase_sql = "AND r.qa_phase = 'verification' " if pre_merge else ""
    # Pre-merge stays on the review transition. At done, keep those review
    # rows (post_deploy-on-review intake) and also consume post-merge phases
    # bound to release or done.
    transition_sql = (
        f"AND r.workflow_transition_id = {marker} "
        if pre_merge
        else (
            f"AND (r.workflow_transition_id = {marker} "
            "OR r.qa_phase IN ('post_deploy', 'manual_acceptance')) "
        )
    )
    params = (
        int(item_id),
        selector_value,
        ITEM_POSTURE_VERIFICATION_TRANSITION,
    )
    # Waived rows stay in this read. A waiver DISCHARGES a case; it does not
    # unbind it, and filtering it out here made the posture look unbound —
    # so an item whose only selected case was waived was refused for having
    # no case at all, which no rerun or authoring could fix.
    cursor = conn.execute(
        "SELECT r.* "
        "FROM qa_requirements r "
        f"WHERE r.item_id = {marker} AND {selector} "
        "AND r.blocking_mode = 'blocking' "
        f"{transition_sql}"
        f"{phase_sql}"
        "ORDER BY r.id",
        params,
    )
    rows = cursor.fetchall()
    scored = []
    for row in rows:
        item = dict(row)
        from yoke_core.domain.qa_simulation_triage import current_simulation_triage

        item["triage_discharge"] = (
            current_simulation_triage(conn, int(item["id"]))
            if item.get("qa_kind") == "simulation"
            else None
        )
        item["passed"] = has_current_passing_run(conn, int(item["id"]))
        scored.append(item)
    rows = scored
    if not rows:
        # A change visible only once deployed selects a post_deploy case bound
        # to the release stage. It binds the posture here and is consumed at
        # done by the completion run's admitted copy, like any post_deploy row.
        if (
            pre_merge
            and conn.execute(
                "SELECT 1 FROM qa_requirements r "
                f"WHERE r.item_id = {marker} AND {selector} "
                "AND r.blocking_mode = 'blocking' "
                f"AND ((r.workflow_transition_id = {marker} "
                "AND r.qa_phase <> 'verification') "
                "OR r.qa_phase = 'post_deploy') LIMIT 1",
                params,
            ).fetchone()
        ):
            return None
        return _failure(
            "GATE_DASH_VERIFICATION_REQUIRED",
            "The selected Dash verification is not bound to a blocking QA case.",
            "Author or materialize the selected case where the Browser "
            "placement reference puts it: a verification case on the review "
            "transition, or a post_deploy case with --target-env bound to the "
            "release stage.",
        )
    unsatisfied_rows = [
        row
        for row in rows
        # A waiver is how a case is discharged, so it is satisfied here even
        # though it never ran. Only the still-open cases belong in this list.
        if not row.get("waived_at")
        and not _requirement_consumed(
            conn,
            row,
            pre_merge=pre_merge,
            item_id=int(item_id),
            candidate_shas=candidate_shas,
        )
    ]
    unsatisfied = [
        int(row["id"] if hasattr(row, "keys") else row[0]) for row in unsatisfied_rows
    ]
    if unsatisfied:
        replacements = [
            int(value)
            for row in unsatisfied_rows
            if (
                value := row.get("replacement_requirement_id")
                or row.get("superseded_by_requirement_id")
            )
        ]
        waiting = next(
            (
                wait
                for value in [*replacements, *unsatisfied]
                if (wait := requirement_awaits_human_review(conn, value)) is not None
            ),
            None,
        )
        if waiting is not None:
            return _failure(
                "GATE_DASH_QA_REVIEW_REQUIRED", waiting.detail, waiting.recovery
            )
        # Executing the case again is the recovery for a case that has not
        # run. It is the wrong instruction for a post_deploy row, whose
        # answer comes from delivery rather than from another run.
        post_deploy = any(
            str(row["qa_phase"] if hasattr(row, "keys") else row[1] or "")
            == "post_deploy"
            for row in unsatisfied_rows
        )
        return _failure(
            "GATE_DASH_VERIFICATION_UNSATISFIED",
            "Selected Dash QA requirement(s) are not satisfied here: "
            + "; ".join(
                f"{row['id']}"
                + (
                    f" ({row['settlement_error']})"
                    if row.get("settlement_error")
                    else ""
                )
                + replacement_note(
                    {
                        "replacement_requirement_id": row.get(
                            "replacement_requirement_id"
                        )
                        or row.get("superseded_by_requirement_id")
                    }
                )
                for row in unsatisfied_rows
            ),
            POST_DEPLOY_RECOVERY
            if post_deploy
            else (
                "Execute each declared replacement (or unreplaced requirement) "
                "through the registered QA case runner and record a passing "
                "independent verdict against the same candidate and scope."
            ),
        )
    return None


__all__ = ["verification_gate"]

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
)
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
) -> bool:
    """Whether this blocking row is satisfied at the boundary being crossed.

    Pre-merge is the original row's own passing run and nothing else. At done
    the shared source-obligation reading decides, and it is asked even for a
    row that has passed: a ``post_deploy`` row's own pass proves the candidate
    that was deployed when it ran, not the one being closed out.
    """
    passed = bool(row["passed"] if hasattr(row, "keys") else row[2])
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
    # rows (YOK-3182 post_deploy-on-review intake) and also consume
    # post-merge phases bound to release or done.
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
    cursor = conn.execute(
        "SELECT r.id, r.qa_phase, EXISTS("
        "SELECT 1 FROM qa_runs qr "
        "WHERE qr.qa_requirement_id = r.id AND qr.verdict = 'pass'"
        ") AS passed "
        "FROM qa_requirements r "
        f"WHERE r.item_id = {marker} AND {selector} "
        "AND r.blocking_mode = 'blocking' AND r.waived_at IS NULL "
        f"{transition_sql}"
        f"{phase_sql}"
        "ORDER BY r.id",
        params,
    )
    rows = cursor.fetchall()
    if not rows:
        if (
            pre_merge
            and conn.execute(
                "SELECT 1 FROM qa_requirements r "
                f"WHERE r.item_id = {marker} AND {selector} "
                "AND r.blocking_mode = 'blocking' AND r.waived_at IS NULL "
                f"AND r.workflow_transition_id = {marker} "
                "AND r.qa_phase <> 'verification' LIMIT 1",
                params,
            ).fetchone()
        ):
            return None
        return _failure(
            "GATE_DASH_VERIFICATION_REQUIRED",
            "The selected Dash verification is not bound to a blocking QA case.",
            "Author or materialize the selected case for the review transition.",
        )
    unsatisfied_rows = [
        row
        for row in rows
        if not _requirement_consumed(
            conn, row, pre_merge=pre_merge, item_id=int(item_id)
        )
    ]
    unsatisfied = [
        int(row["id"] if hasattr(row, "keys") else row[0])
        for row in unsatisfied_rows
    ]
    if unsatisfied:
        waiting = next(
            (
                wait
                for value in unsatisfied
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
            + ", ".join(str(value) for value in unsatisfied),
            POST_DEPLOY_RECOVERY
            if post_deploy
            else "Execute each requirement through the registered QA case runner.",
        )
    return None


__all__ = ["verification_gate"]

"""Runtime authority for definition-bounded Dash item posture."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.dash_path_claim_posture import (
    activation_gate as _path_activation_gate,
    completion_gate as _path_completion_gate,
)
from yoke_core.domain.dash_posture_read import (
    dict_row as _dict_row,
    failure as _failure,
    item_row as _item,
    marker as _p,
    posture as _posture,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)
from yoke_core.domain.schema_common import _table_exists


def approval_policy_for_posture(
    *,
    workflow_id: str,
    posture: Mapping[str, Any],
    target_status: str,
) -> Optional[dict[str, list[Any]]]:
    """Return the explicit owner gate selected by Dash approval posture."""
    if (
        workflow_id != "dash"
        or target_status != "done"
        or posture.get("approval_on_done") is not True
    ):
        return None
    return {"roles": ["owner"], "actors": []}


def approval_policy_for_transition(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
) -> Optional[dict[str, list[Any]]]:
    """Return the explicit v1 owner authority for approval-on-done."""
    item = _item(conn, item_id)
    return approval_policy_for_posture(
        workflow_id=str(item["workflow_id"]),
        posture=_posture(item),
        target_status=target_status,
    )


def _verification_gate(
    conn: Any,
    *,
    item_id: int,
    verification: Mapping[str, Any],
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
    cursor = conn.execute(
        "SELECT r.id, EXISTS("
        "SELECT 1 FROM qa_runs qr "
        "WHERE qr.qa_requirement_id = r.id AND qr.verdict = 'pass'"
        ") AS passed "
        "FROM qa_requirements r "
        f"WHERE r.item_id = {marker} AND {selector} "
        "AND r.blocking_mode = 'blocking' AND r.waived_at IS NULL "
        f"AND r.workflow_transition_id = {marker} "
        "ORDER BY r.id",
        (
            int(item_id),
            selector_value,
            ITEM_POSTURE_VERIFICATION_TRANSITION,
        ),
    )
    rows = cursor.fetchall()
    if not rows:
        return _failure(
            "GATE_DASH_VERIFICATION_REQUIRED",
            "The selected Dash verification is not bound to a blocking QA case.",
            "Author or materialize the selected case for the review transition.",
        )
    unsatisfied = [
        int(row["id"] if hasattr(row, "keys") else row[0])
        for row in rows
        if not bool(row["passed"] if hasattr(row, "keys") else row[1])
    ]
    if unsatisfied:
        return _failure(
            "GATE_DASH_VERIFICATION_UNSATISFIED",
            "Selected Dash QA requirement(s) lack a passing run: "
            + ", ".join(str(value) for value in unsatisfied),
            "Execute each requirement through the registered QA case runner.",
        )
    return None


def _evidence(conn: Any, item_id: int) -> Optional[dict[str, Any]]:
    from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
    from yoke_core.domain.item_json_sections import read_json_section

    return read_json_section(
        conn,
        item_id=item_id,
        section=DASH_EVIDENCE_SECTION,
    )


def _approval_gate(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    from yoke_core.domain.decision_requests import list_subject_requests

    history = list_subject_requests(
        conn,
        "item_transition",
        f"{int(item_id)}:done",
    )
    latest = history[0] if history else None
    if (
        latest is not None
        and latest["status"] == "resolved"
        and latest["resolution_action"] == "approve"
    ):
        return None
    return _failure(
        "GATE_DASH_APPROVAL_REQUIRED",
        "Approval-on-done is waiting for a project owner decision.",
        "Resolve the lifecycle decision request through the Inbox.",
    )


def _same_git_identity(left: str, right: str) -> bool:
    first = left.strip().casefold()
    second = right.strip().casefold()
    return (
        len(first) >= 7
        and len(second) >= 7
        and (first.startswith(second) or second.startswith(first))
    )


def _deployment_gate(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    evidence = _evidence(conn, item_id)
    merge_sha = str((evidence or {}).get("merge_sha") or "")
    if not merge_sha:
        return _failure(
            "GATE_DASH_DEPLOYMENT_EVIDENCE_REQUIRED",
            "Deploy-after-merge needs the persisted merge identity.",
            "Record Dash merge evidence, then run item-bound delivery.",
        )
    if not all(
        _table_exists(conn, table)
        for table in (
            "deployment_runs",
            "deployment_run_items",
        )
    ):
        return _failure(
            "GATE_DASH_DEPLOYMENT_REQUIRED",
            "Deploy-after-merge has no item-bound deployment-run authority.",
            "Start and complete a deployment run for this item.",
        )
    marker = _p(conn)
    row = _dict_row(
        conn.execute(
            "SELECT dr.id, dr.status, COALESCE(dr.release_lineage, '') "
            "AS release_lineage FROM deployment_runs dr "
            "JOIN deployment_run_items dri ON dri.run_id = dr.id "
            f"WHERE dri.item_id = {marker} "
            "ORDER BY dr.created_at DESC, dr.id DESC LIMIT 1",
            (int(item_id),),
        )
    )
    if row is None or str(row["status"]) != "succeeded":
        return _failure(
            "GATE_DASH_DEPLOYMENT_REQUIRED",
            "The latest item-bound deployment run has not succeeded.",
            "Run the selected project delivery flow to completion.",
        )
    lineage = str(row.get("release_lineage") or "")
    if not _same_git_identity(lineage, merge_sha):
        return _failure(
            "GATE_DASH_DEPLOYMENT_LINEAGE",
            "The successful deployment run does not target the recorded merge.",
            "Deploy the recorded merged commit through an item-bound run.",
        )
    return None


def evaluate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict[str, Any]]:
    """Evaluate every selected Dash posture fact at its lifecycle boundary."""
    conn = connect(db_path)
    try:
        item = _item(conn, int(item_id))
        if str(item["workflow_id"]) != "dash":
            return None
        posture = _posture(item)
        if target_status == "implementing" and posture.get("path_claims") is True:
            return _path_activation_gate(conn, int(item_id))
        verification = posture.get("verification")
        if target_status in {
            ITEM_POSTURE_VERIFICATION_TRANSITION,
            "done",
        } and isinstance(verification, Mapping):
            blocked = _verification_gate(
                conn,
                item_id=int(item_id),
                verification=verification,
            )
            if blocked is not None:
                return blocked
        if target_status != "done":
            return None
        if posture.get("path_claims") is True:
            blocked = _path_completion_gate(conn, int(item_id))
            if blocked is not None:
                return blocked
        if posture.get("approval_on_done") is True:
            blocked = _approval_gate(conn, int(item_id))
            if blocked is not None:
                return blocked
        if posture.get("deployment") is True:
            return _deployment_gate(conn, int(item_id))
        return None
    finally:
        conn.close()


__all__ = [
    "approval_policy_for_posture",
    "approval_policy_for_transition",
    "evaluate",
]

"""Runtime authority for definition-bounded Dash item posture."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.approval_policy import ApprovalPolicy
from yoke_core.domain.dash_path_claim_posture import (
    activation_gate as _path_activation_gate,
    completion_gate as _path_completion_gate,
)
from yoke_core.domain.deployment_run_candidate_containment import (
    UNDETERMINED as _CONTAINMENT_UNDETERMINED,
    candidate_contains_commit,
)
from yoke_core.domain.delivery_evidence_ladder import (
    UNDETERMINED_DELIVERY as _DELIVERY_UNDETERMINED,
    delivery_evidence,
)
from yoke_core.domain.deployment_qa_source_obligation import latest_completion_run
from yoke_core.domain.dash_posture_read import (
    failure as _failure,
    item_row as _item,
    posture as _posture,
)
from yoke_core.domain.dash_posture_verification_gate import verification_gate
from yoke_core.domain.relayed_containment_attestation import (
    take_relayed_verdict,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deploy_pipeline_environment import watch_deploy_command
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


def approval_policy_for_posture(
    *,
    workflow_id: str,
    posture: Mapping[str, Any],
    target_status: str,
) -> Optional[ApprovalPolicy]:
    """Return the explicit owner gate selected by Dash approval posture."""
    if (
        workflow_id != "dash"
        or target_status != "done"
        or posture.get("approval_on_done") is not True
    ):
        return None
    return ApprovalPolicy(roles=("owner",))


def approval_policy_for_transition(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
) -> Optional[ApprovalPolicy]:
    """Return the explicit owner authority selected by approval-on-done."""
    item = _item(conn, item_id)
    return approval_policy_for_posture(
        workflow_id=str(item["workflow_id"]),
        posture=_posture(item),
        target_status=target_status,
    )


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
    from yoke_core.domain.decision_request_authority import request_deciders

    if (
        latest is not None
        and latest["status"] == "pending"
        and not request_deciders(conn, int(latest["id"]))
    ):
        return _failure(
            "GATE_DASH_APPROVAL_REQUIRED",
            "Approval-on-done has no eligible human project owner who can answer.",
            "Grant the project owner role to a human actor, then resolve the "
            "Inbox request. Do not assign roles automatically.",
        )
    return _failure(
        "GATE_DASH_APPROVAL_REQUIRED",
        "Approval-on-done is waiting for a project owner decision.",
        "Resolve the lifecycle decision request through the Inbox.",
    )


def _active_lane_head(conn: Any, item_id: int) -> str:
    if not (
        _table_exists(conn, "item_worktrees")
        and _column_exists(conn, "item_worktrees", "commit_sha")
    ):
        return ""
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT commit_sha FROM item_worktrees "
        f"WHERE item_id = {marker} AND state = 'active' "
        "AND commit_sha IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return ""
    value = row["commit_sha"] if hasattr(row, "keys") else row[0]
    return str(value or "").strip()


def _lineage_covers(
    conn: Any,
    project_id: int,
    *,
    lineage: str,
    commit_sha: str,
    item_id: int = 0,
    run_id: str = "",
) -> Optional[dict[str, Any]]:
    verdict = candidate_contains_commit(
        conn,
        int(project_id),
        candidate_lineage=lineage,
        commit_sha=commit_sha,
    )
    if verdict.state == _CONTAINMENT_UNDETERMINED:
        # This host could not look. The client that merged the item was
        # standing in the lane and could, so its relayed answer is consulted
        # here and nowhere else -- a host with its own answer keeps it.
        verdict = take_relayed_verdict(
            verdict,
            conn,
            item_id=int(item_id),
            run_id=run_id,
            candidate=lineage,
            commit_sha=commit_sha,
        )
    if verdict.state == _CONTAINMENT_UNDETERMINED:
        return _failure(
            "GATE_DASH_DEPLOYMENT_CONTAINMENT_UNDETERMINED",
            "Whether the deployed candidate contains the current work could "
            f"not be determined ({verdict.reason}).",
            f"{verdict.recovery} Do not redeploy to make this merge the "
            "candidate tip; the other members of that release would then fail "
            "the same way.",
        )
    if not verdict.contained:
        return _failure(
            "GATE_DASH_DEPLOYMENT_LINEAGE",
            "The successful deployment run does not contain this item's "
            "current candidate.",
            "Deliver this item through a run whose candidate contains its "
            "merge and live lane head.",
        )
    return None


def _stale_completion_run_gate(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    """Refuse a succeeded run that does not contain the live lane head.

    Selected deployment posture still requires a succeeded run and still
    contains the recorded merge. This narrower check runs even when that
    posture is off: a first-landing run must not close the item while a
    newer same-item head is unmerged or undeployed.
    """
    head = _active_lane_head(conn, item_id)
    if not head:
        return None
    row = latest_completion_run(conn, int(item_id))
    if row is None or str(row["status"]) != "succeeded":
        return None
    return _lineage_covers(
        conn,
        int(row["project_id"]),
        lineage=str(row.get("release_lineage") or ""),
        commit_sha=head,
        item_id=int(item_id),
        run_id=str(row["id"]),
    )


def _deployment_gate(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    # Containment stays here so verification-phase intake can land apart.
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
    # Membership, then containment — the shared ladder the done engine
    # reads, so both answer one release the same way. A batch has exactly
    # one tip, so requiring the run to be pinned to this item's merge could
    # only ever pass a release of one item; every other member would be told
    # to redeploy until its own merge became the tip, which the batch it
    # shipped in cannot satisfy.
    evidence_verdict = delivery_evidence(conn, int(item_id))
    if evidence_verdict.state == _DELIVERY_UNDETERMINED:
        return _failure(
            "GATE_DASH_DEPLOYMENT_CONTAINMENT_UNDETERMINED",
            "Whether the deployed candidate contains the current work could "
            f"not be determined ({evidence_verdict.reason}).",
            f"{evidence_verdict.recovery} Do not redeploy to make this merge "
            "the candidate tip; the other members of that release would then "
            "fail the same way.",
        )
    if not evidence_verdict.discharged:
        row = latest_completion_run(conn, int(item_id))
        prepared = row is not None and str(row["status"]) == "created"
        return _failure(
            "GATE_DASH_DEPLOYMENT_REQUIRED",
            (
                f"Prepared deployment run {row['id']} has not been executed."
                if prepared
                else f"No succeeded run of the selected flow delivers this "
                f"item ({evidence_verdict.reason})."
            ),
            (
                f"Execute it: {watch_deploy_command(str(row['id']))}"
                if prepared
                else evidence_verdict.recovery
            ),
        )
    # Delivery having happened is not this posture's whole question. It also
    # requires the deployed candidate to contain this item's merge, which the
    # ladder deliberately does not decide — a run can list the item as a
    # member while shipping a revision that predates its merge.
    blocked = _lineage_covers(
        conn,
        int(evidence_verdict.project_id or 0),
        lineage=evidence_verdict.release_lineage,
        commit_sha=merge_sha,
        item_id=int(item_id),
        run_id=evidence_verdict.run_id,
    )
    if blocked is not None:
        return blocked
    return _stale_completion_run_gate(conn, item_id)


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
            blocked = verification_gate(
                conn,
                item_id=int(item_id),
                verification=verification,
                target_status=target_status,
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
        return _stale_completion_run_gate(conn, int(item_id))
    finally:
        conn.close()


__all__ = [
    "approval_policy_for_posture",
    "approval_policy_for_transition",
    "evaluate",
]

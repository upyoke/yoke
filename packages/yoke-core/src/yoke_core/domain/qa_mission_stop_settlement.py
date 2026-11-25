"""Settle mission dockets when a stopped walk never captured product proof."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import marker, result_rows
from yoke_core.domain.qa_run_verdict_record import update_qa_run


# Restore receipts and blocker notes record a walk's setup, never its product proof.
NON_PROOF_ARTIFACT_TYPES = ("diagnostic", "starting_state_restore")


def mission_review_cases(
    conn: Any, cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Project live mission evidence over the frozen bundle.

    Preparation freezes a mission case before its walker runs, so each read
    re-reads the capture run's artifacts and degraded reason. A mission that
    settled before capturing proof leaves the review entirely.
    """
    from yoke_core.domain.qa_review_evidence import capture_artifacts

    reviewable = []
    p = marker(conn)
    for case in cases:
        if (
            case.get("capture_runner") != "agent_mission"
            or case.get("capture_run_id") is None
            or case.get("requirement_id") is None
        ):
            reviewable.append(case)
            continue
        run_id, requirement_id = int(case["capture_run_id"]), int(case["requirement_id"])
        run = query_one(
            conn,
            "SELECT capture_degraded_reason,verdict,case_outcome FROM qa_runs "
            f"WHERE id={p} AND qa_requirement_id={p} AND performed_by='agent_mission'",
            (run_id, requirement_id),
        )
        if run is None:
            reviewable.append(case)
            continue
        reason = run["capture_degraded_reason"]
        if (
            run["verdict"] is None
            and run["case_outcome"] == "blocked_on_precondition"
            and str(reason or "").startswith("mission_setup_blocked:")
        ):
            continue
        artifacts = capture_artifacts(conn, requirement_id=requirement_id, run_id=run_id)
        proven = any(
            artifact["artifact_type"] not in NON_PROOF_ARTIFACT_TYPES
            for artifact in artifacts
        )
        reviewable.append(
            {
                **case,
                "artifacts": artifacts,
                "capture_degraded_reason": None if proven else reason,
            }
        )
    return reviewable


def settle_stopped_mission_dockets(
    conn: Any, execution: dict[str, Any], *, reason: str
) -> None:
    """Keep diagnostics, but never offer a setup-only docket for judgment.

    The docket keeps a NULL verdict: a walk that never started proves nothing
    about the product, so the gate reads it as unrun rather than red.
    """
    if not reason.startswith("blocked_on_precondition:"):
        return
    missions = {
        int(case["requirement_id"])
        for case in execution.get("roster") or []
        if case.get("runner_id") == "agent_mission"
    }
    if not missions:
        return
    p = marker(conn)
    for row in result_rows(conn, str(execution["id"])):
        if int(row["requirement_id"]) not in missions:
            continue
        run_id = row["result"].get("run_id")
        if not run_id:
            continue
        capture = query_one(
            conn,
            f"SELECT verdict FROM qa_runs WHERE id={p} AND qa_requirement_id={p} "
            "AND performed_by='agent_mission'",
            (int(run_id), int(row["requirement_id"])),
        )
        if capture is None or capture["verdict"] is not None:
            continue
        proof = query_one(
            conn,
            f"SELECT id FROM qa_artifacts WHERE qa_run_id={p} "
            f"AND artifact_type NOT IN ({p},{p}) LIMIT 1",
            (int(run_id), *NON_PROOF_ARTIFACT_TYPES),
        )
        if proof is not None:
            continue
        diagnostic = (
            f"mission_setup_blocked: {reason}; no product proof was captured. "
            "Resolve the named prerequisite, then run a fresh mission."
        )
        update_qa_run(
            conn,
            int(run_id),
            {
                "execution_status": "capture_failed",
                "case_outcome": "blocked_on_precondition",
                "verdict_reason": diagnostic,
                "capture_degraded_reason": diagnostic,
            },
            unjudged_only=True,
            default_completed_at=utc_now(),
        )

    bundle = query_one(
        conn,
        f"SELECT bundle_json FROM qa_plan_review_bundles WHERE execution_id={p} "
        "AND state='pending'",
        (str(execution["id"]),),
    )
    if bundle is not None and not mission_review_cases(
        conn, json.loads(bundle["bundle_json"]).get("cases") or []
    ):
        conn.execute(
            "UPDATE qa_plan_review_bundles SET state='completed' "
            f"WHERE execution_id={p} AND state='pending'",
            (str(execution["id"]),),
        )


def stopped_mission_guidance(
    subject_flag: str, execution_id: str, *, has_host: bool = True
) -> str:
    """Teach the same terminal recovery where mission owners choose a verdict."""
    cleanup = "finish walk-end " if has_host else "clean up controller fixtures "
    return (
        "If setup stops a mission before product proof, attach blocker evidence as `diagnostic`, "
        + cleanup
        + "and abort this execution with `yoke qa plan abort "
        f"{subject_flag} --execution-id {execution_id} --reason "
        "'blocked_on_precondition: <prerequisite and recovery>'` "
        "(at most 200 characters; cite the Progress Log for detail). "
        "Diagnostics and restore receipts alone are not product proof; "
        "the stopped docket settles as mission_setup_blocked with no verdict "
        "and without human review. Resolve the prerequisite before a fresh run. "
    )

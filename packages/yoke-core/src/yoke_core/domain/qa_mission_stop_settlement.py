"""Settle mission dockets when a stopped walk never captured product proof."""

from __future__ import annotations

from typing import Any

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_execution_store import marker, result_rows
from yoke_core.domain.qa_run_verdict_record import update_qa_run


def mission_review_cases(
    conn: Any, cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Project frozen bundles without missions that settled before capturing proof."""
    reviewable = []
    p = marker(conn)
    for case in cases:
        stopped = None
        if (
            case.get("capture_runner") == "agent_mission"
            and case.get("capture_run_id") is not None
            and case.get("requirement_id") is not None
        ):
            stopped = query_one(
                conn,
                f"SELECT capture_degraded_reason FROM qa_runs WHERE id={p} AND qa_requirement_id={p} "
                "AND performed_by='agent_mission' AND verdict='error' "
                "AND case_outcome='blocked_on_precondition'",
                (int(case["capture_run_id"]), int(case["requirement_id"])),
            )
        if stopped is None or not str(
            stopped["capture_degraded_reason"] or ""
        ).startswith("mission_setup_blocked:"):
            reviewable.append(case)
    return reviewable


def settle_stopped_mission_dockets(
    conn: Any, execution: dict[str, Any], *, reason: str
) -> None:
    """Keep diagnostics, but never offer a setup-only docket for judgment."""
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
            "AND artifact_type NOT IN ('diagnostic','starting_state_restore') LIMIT 1",
            (int(run_id),),
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
                "verdict": "error",
                "verdict_reason": diagnostic,
                "capture_degraded_reason": diagnostic,
            },
            unjudged_only=True,
            default_completed_at=utc_now(),
        )


def stopped_mission_guidance(subject_flag: str, execution_id: str) -> str:
    """Teach the same terminal recovery where mission owners choose a verdict."""
    return (
        "If setup stops a mission before product proof, finish walk-end "
        "and abort this execution with `yoke qa plan abort "
        f"{subject_flag} --execution-id {execution_id} --reason "
        "'blocked_on_precondition: <prerequisite and recovery>'`. "
        "Diagnostics and restore receipts alone are not product proof; "
        "the stopped docket settles as mission_setup_blocked/error "
        "without human review. Resolve the prerequisite before a fresh run. "
    )

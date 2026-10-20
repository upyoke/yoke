"""Read a QA capture whose independent agent review is still pending.

A plan execution that finished deterministic capture and opened a review
bundle stands at ``awaiting_agent_review``: the capture is complete and no
QA verdict exists yet. An execution aborted or errored mid-walk keeps a
pending bundle for its completed captures, so it owes the same review. The
verdict belongs to the reviewer that submits that bundle, never to the
session that ran the capture. These readers let the verdict writes refuse a
capture-side verdict on such a requirement, and let a deployment stage tell
"review pending" apart from "never executed".

Nothing here writes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.qa_constants import is_agent_reviewed_case
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.refusal_recovery import compose_refusal

_PENDING_REVIEW_SQL = (
    "SELECT e.id AS execution_id, e.session_id AS session_id, e.state AS state, "
    "e.item_id,e.deployment_run_id,e.deployment_stage,e.deployment_member_item_id,"
    "e.execution_target_digest,b.id AS bundle_id, b.bundle_json AS bundle_json "
    "FROM qa_plan_executions e "
    "JOIN qa_plan_review_bundles b ON b.execution_id = e.id "
    "WHERE e.state IN ('awaiting_agent_review','aborted','error') "
    "AND b.state = 'pending'"
)


def review_scope_flag(conn: Any, execution: Mapping[str, Any]) -> str:
    """The subject flag ``review-begin`` and ``adopt`` take for this execution."""
    if execution.get("deployment_run_id"):
        return f"--deployment-run-id {execution['deployment_run_id']}"
    if execution.get("item_id"):
        from yoke_core.domain.project_identity import render_item_ref

        return f"--item {render_item_ref(conn, int(execution['item_id']))}"
    return "--project PROJECT"


@dataclass(frozen=True)
class PendingAgentReview:
    """One execution whose completed captures wait on a pending review bundle."""

    execution_id: str
    bundle_id: str
    session_id: str
    state: str = "awaiting_agent_review"
    scope_flag: str = ""

    def review_begin_command(self) -> str:
        return (
            f"yoke qa plan review-begin {self.scope_flag} "
            f"--execution-id {self.execution_id}"
        )

    def next_action(self) -> str:
        """The review step that settles this execution."""
        return (
            "the session that ran the capture "
            f"({self.session_id or 'unrecorded'}) runs "
            f"`{self.review_begin_command()}`, dispatches the reviewer the "
            "returned bundle names, and submits its complete verdict batch "
            "with `yoke qa plan review-submit`; when that session has ended, "
            "its successor first runs `yoke qa plan adopt "
            f"{self.scope_flag} --execution-id {self.execution_id} --reason "
            '"Review captured QA after restaffing"`. Re-running `yoke qa plan '
            "run` cannot supply this verdict; the requirement and stage settle "
            "from the submission"
        )


def _pending(conn: Any, row: Any) -> PendingAgentReview:
    return PendingAgentReview(
        execution_id=str(row["execution_id"]),
        bundle_id=str(row["bundle_id"]),
        session_id=str(row["session_id"] or ""),
        state=str(row["state"]),
        scope_flag=review_scope_flag(conn, row),
    )


def _bundle_requirement_ids(bundle_json: Any) -> set[int]:
    try:
        bundle = json.loads(str(bundle_json or "{}"))
    except ValueError:
        return set()
    cases = bundle.get("cases") if isinstance(bundle, dict) else None
    return {
        int(case["requirement_id"])
        for case in cases or []
        if isinstance(case, dict) and case.get("requirement_id") is not None
    }


def pending_review_for_requirement(
    conn: Any, requirement_id: int
) -> PendingAgentReview | None:
    """The pending review bundle that owns this requirement's verdict."""
    for row in conn.execute(_PENDING_REVIEW_SQL).fetchall():
        if int(requirement_id) in _bundle_requirement_ids(row["bundle_json"]):
            return _pending(conn, row)
    return None


def stopped_review_requirements(
    conn: Any, requirement_ids: Iterable[int]
) -> dict[int, PendingAgentReview]:
    """Requirements an aborted or errored execution's pending review still owns.

    A new roster leaves these out: their verdict comes only from that review,
    so recapturing them would race it.
    """
    wanted = {int(value) for value in requirement_ids}
    if not wanted:
        return {}
    held: dict[int, PendingAgentReview] = {}
    rows = conn.execute(
        f"{_PENDING_REVIEW_SQL} AND e.state IN ('aborted','error') "
        "ORDER BY e.created_at, e.id"
    ).fetchall()
    for row in rows:
        for requirement_id in _bundle_requirement_ids(row["bundle_json"]) & wanted:
            held.setdefault(requirement_id, _pending(conn, row))
    return held


def pending_review_for_stage(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> PendingAgentReview | None:
    """The live scoped execution for this stage subject awaiting review."""
    from yoke_core.domain.deployment_qa_acceptance_reads import presented_pending_review

    row, scoped = presented_pending_review(
        conn, run_id, stage_name, member_item_id, execution_target_digest
    )
    if scoped:
        return _pending(conn, row) if row is not None else None
    p = marker(conn)
    row = conn.execute(
        f"{_PENDING_REVIEW_SQL} AND e.deployment_run_id = {p} "
        f"AND e.deployment_stage = {p} "
        f"AND COALESCE(e.deployment_member_item_id, 0) = {p} "
        f"AND e.execution_target_digest = {p} "
        "ORDER BY e.created_at DESC, e.id DESC LIMIT 1",
        (run_id, stage_name, member_item_id or 0, execution_target_digest),
    ).fetchone()
    return _pending(conn, row) if row is not None else None


def capture_verdict_refusal(pending: PendingAgentReview, requirement_id: int) -> str:
    """Refuse a verdict written beside a pending independent review."""
    return compose_refusal(
        f"requirement {requirement_id} is captured and its independent agent "
        "review is pending; its verdict comes only from that review",
        evaluated=(
            f"plan execution {pending.execution_id} is {pending.state} "
            f"with pending review bundle {pending.bundle_id}; a capture-side "
            "verdict would report a pass or fail no reviewer recorded"
        ),
        recovery=pending.next_action(),
    )


def pending_review_verdict_refusal(
    conn: Any, requirement_id: int, verdict: object, requirement: Mapping[str, Any]
) -> str | None:
    """The refusal for a verdict write while this requirement's review is pending.

    Writes that carry no verdict -- capture status, artifacts -- are not
    verdicts and pass through untouched, and only an agent-reviewed case
    (``requirement`` carries its ``verdict_path`` and ``method_id``) can ever
    sit in a review bundle, so every other requirement skips the lookup.
    """
    if verdict is None or not is_agent_reviewed_case(
        requirement.get("verdict_path"), requirement.get("method_id")
    ):
        return None
    pending = pending_review_for_requirement(conn, requirement_id)
    if pending is None:
        return None
    return capture_verdict_refusal(pending, requirement_id)


def stage_review_pending_blocker(pending: PendingAgentReview) -> str:
    """Stage wait line for captures whose independent review is pending."""
    return compose_refusal(
        "scoped QA captures are recorded and independent agent review is "
        "pending; no QA verdict exists yet",
        evaluated=(
            f"plan execution {pending.execution_id} is {pending.state} "
            f"with pending review bundle {pending.bundle_id}"
        ),
        recovery=pending.next_action(),
    )


__all__ = [
    "PendingAgentReview",
    "capture_verdict_refusal",
    "pending_review_for_requirement",
    "pending_review_for_stage",
    "pending_review_verdict_refusal",
    "review_scope_flag",
    "stage_review_pending_blocker",
    "stopped_review_requirements",
]

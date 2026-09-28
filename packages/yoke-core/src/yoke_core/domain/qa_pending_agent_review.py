"""Read a QA capture whose independent agent review is still pending.

A plan execution that finished deterministic capture and opened a review
bundle stands at ``awaiting_agent_review``: the capture is complete and no
QA verdict exists yet. The verdict belongs to the reviewer that submits
that bundle, never to the session that ran the capture. These readers let
the verdict writes refuse a capture-side verdict on such a requirement, and
let a deployment stage tell "review pending" apart from "never executed".

Nothing here writes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.qa_constants import is_agent_reviewed_case
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.refusal_recovery import compose_refusal

_PENDING_REVIEW_SQL = (
    "SELECT e.id AS execution_id, e.session_id AS session_id, "
    "b.id AS bundle_id, b.bundle_json AS bundle_json "
    "FROM qa_plan_executions e "
    "JOIN qa_plan_review_bundles b ON b.execution_id = e.id "
    "WHERE e.state = 'awaiting_agent_review' AND b.state = 'pending'"
)


@dataclass(frozen=True)
class PendingAgentReview:
    """One live execution whose capture is complete and review is pending."""

    execution_id: str
    bundle_id: str
    session_id: str

    def next_action(self) -> str:
        """The existing review step that settles this execution."""
        return (
            "the session that ran the capture "
            f"({self.session_id or 'unrecorded'}) re-runs the same "
            "`yoke qa plan run` (or `yoke watch qa-plan`) invocation, which "
            "reprints the pending review bundle without recapturing, "
            "dispatches the reviewer that bundle names, and submits its "
            "complete verdict batch with `yoke qa plan review-submit`; the "
            "requirement and stage settle from that submission"
        )


def _pending(row: Any) -> PendingAgentReview:
    return PendingAgentReview(
        execution_id=str(row["execution_id"]),
        bundle_id=str(row["bundle_id"]),
        session_id=str(row["session_id"] or ""),
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
            return _pending(row)
    return None


def pending_review_for_stage(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> PendingAgentReview | None:
    """The live scoped execution for this stage subject awaiting review."""
    p = marker(conn)
    row = conn.execute(
        f"{_PENDING_REVIEW_SQL} AND e.deployment_run_id = {p} "
        f"AND e.deployment_stage = {p} "
        f"AND COALESCE(e.deployment_member_item_id, 0) = {p} "
        f"AND e.execution_target_digest = {p} "
        "ORDER BY e.created_at DESC, e.id DESC LIMIT 1",
        (run_id, stage_name, member_item_id or 0, execution_target_digest),
    ).fetchone()
    return _pending(row) if row is not None else None


def capture_verdict_refusal(pending: PendingAgentReview, requirement_id: int) -> str:
    """Refuse a verdict written beside a pending independent review."""
    return compose_refusal(
        f"requirement {requirement_id} is captured and its independent agent "
        "review is pending; its verdict comes only from that review",
        evaluated=(
            f"plan execution {pending.execution_id} is awaiting_agent_review "
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
    """Stage wait line for a completed capture whose review is pending."""
    return compose_refusal(
        "scoped QA capture is complete and independent agent review is "
        "pending; no QA verdict exists yet",
        evaluated=(
            f"plan execution {pending.execution_id} is awaiting_agent_review "
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
    "stage_review_pending_blocker",
]

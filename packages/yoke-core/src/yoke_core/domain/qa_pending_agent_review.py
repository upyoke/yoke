"""Read a QA capture whose independent agent review is still pending.

A plan execution that finished deterministic capture and opened a review
bundle stands at ``walking`` until mission hand-back, then
``awaiting_walk_review``: the capture is complete and no
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

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.qa_constants import is_agent_reviewed_case
from yoke_core.domain.qa_plan_execution_store import marker

_PENDING_REVIEW_SQL = (
    "SELECT e.id AS execution_id, e.session_id AS session_id, e.state AS state, "
    "e.item_id,e.deployment_run_id,e.deployment_stage,e.deployment_member_item_id,"
    "e.execution_target_digest,e.test_machine_lease_id,"
    "s.ended_at IS NOT NULL AS owner_ended,"
    "b.id AS bundle_id, b.bundle_json AS bundle_json "
    "FROM qa_plan_executions e "
    "JOIN qa_plan_review_bundles b ON b.execution_id = e.id "
    "LEFT JOIN harness_sessions s ON s.session_id = e.session_id "
    "WHERE e.state IN ('walking','awaiting_walk_review','aborted','error') "
    "AND b.state = 'pending'"
)


def review_scope_flag(conn: Any, execution: Mapping[str, Any]) -> str:
    """The subject flag ``review-begin`` and ``adopt`` take for this execution."""
    if execution.get("item_id"):
        from yoke_core.domain.project_identity import render_item_ref

        return f"--item {render_item_ref(conn, int(execution['item_id']))}"
    return ""


@dataclass(frozen=True)
class PendingAgentReview:
    """One execution whose completed captures wait on a pending review bundle."""

    execution_id: str
    bundle_id: str
    session_id: str
    state: str = "awaiting_walk_review"
    scope_flag: str = ""
    execution_target_digest: str = ""
    #: The Test Machine a walking mission holds, when it holds one.
    test_machine: str = ""
    owner_ended: bool = False

    def review_begin_command(self) -> str:
        return (
            "yoke qa plan review-begin "
            + (f"{self.scope_flag} " if self.scope_flag else "")
            + f"--execution-id {self.execution_id}"
        )

    @property
    def abandoned_walk(self) -> bool:
        return self.owner_ended and self.state in {"walking", "awaiting_walk_review"}

    def next_action(self) -> str:
        """The review step that settles this execution.

        A ``walking`` mission is still capturing: no review command applies
        until walk-end moves it to ``awaiting_walk_review``.
        """
        if self.abandoned_walk:
            scope = f"{self.scope_flag} " if self.scope_flag else ""
            return (
                f"Settle the abandoned execution with `yoke qa plan abort "
                f"{scope}--execution-id {self.execution_id} --reason TEXT`. "
                "Follow its restore instructions if the execution still holds a Test Machine."
            )
        if self.state == "walking":
            where = f" on {self.test_machine}" if self.test_machine else ""
            return (
                f"mission walk in progress{where} (plan execution "
                f"{self.execution_id}, session {self.session_id or 'unrecorded'}); "
                "the walking session completes the walk in its main thread and "
                "submits its cited verdict through the review bundle"
            )
        return (
            "the session that ran the capture "
            f"({self.session_id or 'unrecorded'}) runs "
            f"`{self.review_begin_command()}`, follows the typed continuation the "
            "returned bundle names, and submits its complete verdict batch "
            "with `yoke qa plan review-submit`; when that session has ended, "
            "its successor first runs `yoke qa plan adopt "
            + (f"{self.scope_flag} " if self.scope_flag else "")
            + f"--execution-id {self.execution_id} --reason "
            '"Review captured QA after restaffing"`. Re-running `yoke qa plan '
            "run` cannot supply this verdict; the requirement and stage settle "
            "from the submission"
        )


def _lease_machine(conn: Any, row: Any) -> str:
    """The Test Machine a walking execution's lease names, if any."""
    lease = row["test_machine_lease_id"] if row["state"] == "walking" else None
    if lease is None:
        return ""
    from yoke_core.domain.schema_work_claim_sql import scope_text_sql

    found = conn.execute(
        f"SELECT {scope_text_sql(conn, 'scope', 'test_machine')} FROM work_claims "
        f"WHERE id={marker(conn)}",
        (int(lease),),
    ).fetchone()
    return str(found[0] or "") if found is not None else ""


def _pending(conn: Any, row: Any) -> PendingAgentReview:
    return PendingAgentReview(
        test_machine=_lease_machine(conn, row),
        execution_id=str(row["execution_id"]),
        bundle_id=str(row["bundle_id"]),
        session_id=str(row["session_id"] or ""),
        state=str(row["state"]),
        scope_flag=review_scope_flag(conn, row),
        execution_target_digest=str(row["execution_target_digest"] or ""),
        owner_ended=bool(row["owner_ended"]),
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


def pending_review_requirements(
    conn: Any, requirement_ids: Iterable[int], *, stopped_only: bool = False
) -> dict[int, PendingAgentReview]:
    """The pending review that owns each of these requirements' verdicts.

    ``stopped_only`` keeps only reviews an aborted or errored execution
    left. Roster admission compares their frozen targets before excluding
    requirements, since only recapturing the same target races that review.
    """
    wanted = {int(value) for value in requirement_ids}
    if not wanted:
        return {}
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    stopped = " AND e.state IN ('aborted','error')" if stopped_only else ""
    held: dict[int, PendingAgentReview] = {}
    # Decode each bundle once per presentation, including unmatched bundles.
    # A stage walk asks separately for every member's requirements.
    def read():
        by_requirement: dict[int, Any] = {}
        rows = conn.execute(
            f"{_PENDING_REVIEW_SQL}{stopped} ORDER BY e.created_at, e.id"
        ).fetchall()
        for row in rows:
            for requirement_id in _bundle_requirement_ids(row["bundle_json"]):
                by_requirement.setdefault(requirement_id, row)
        return by_requirement

    rows = presentation_read(
        conn, ("qa_pending_review_index", stopped_only), read
    )
    for requirement_id in wanted & rows.keys():
        held[requirement_id] = _pending(conn, rows[requirement_id])
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
    if pending.abandoned_walk:
        return compose_refusal(
            f"requirement {requirement_id} belongs to a walk whose owner has ended",
            evaluated=f"execution {pending.execution_id} still holds its capture",
            recovery=pending.next_action(),
        )
    walking = pending.state == "walking"
    return compose_refusal(
        f"requirement {requirement_id} belongs to a mission walk still in "
        "progress; the walking session submits its verdict through the review bundle"
        if walking
        else f"requirement {requirement_id} is captured and its independent agent "
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
    if pending.abandoned_walk:
        return compose_refusal(
            "scoped QA walk owner has ended",
            evaluated=f"execution {pending.execution_id} is still {pending.state}",
            recovery=pending.next_action(),
        )
    return compose_refusal(
        (
            "scoped QA mission walk is in progress; the verdict is pending"
            if pending.state == "walking"
            else "scoped QA captures are recorded and independent agent review is "
            "pending; no QA verdict exists yet"
        ),
        evaluated=(
            f"plan execution {pending.execution_id} is walking; its session is "
            f"still capturing against mission work order {pending.bundle_id}"
            if pending.state == "walking"
            else f"plan execution {pending.execution_id} is {pending.state} "
            f"with pending review bundle {pending.bundle_id}"
        ),
        recovery=pending.next_action(),
    )


__all__ = [
    "PendingAgentReview",
    "capture_verdict_refusal",
    "pending_review_for_requirement",
    "pending_review_for_stage",
    "pending_review_requirements",
    "pending_review_verdict_refusal",
    "review_scope_flag",
    "stage_review_pending_blocker",
]

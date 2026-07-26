"""Decision-request producer and consumer for QA evidence review."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
)
from yoke_core.domain.schema_common import _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _requirement(conn: Any, requirement_id: int) -> dict[str, Any]:
    p = _p(conn)
    row = conn.execute(
        "SELECT id, item_id, epic_id, deployment_run_id, plan_id, "
        "qa_kind, success_policy FROM qa_requirements "
        f"WHERE id = {p}",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        raise LookupError(f"QA requirement {requirement_id} does not exist")
    value = {key: row[key] for key in row.keys()}
    if value.get("plan_id") is not None:
        project = conn.execute(
            f"SELECT project_id, name FROM qa_plans WHERE id = {p}",
            (int(value["plan_id"]),),
        ).fetchone()
        if project is not None:
            value["project_id"] = int(project[0])
            value["plan_name"] = str(project[1])
    item_id = value.get("item_id") or value.get("epic_id")
    if value.get("project_id") is None and item_id is not None:
        project = conn.execute(
            f"SELECT project_id, title FROM items WHERE id = {p}",
            (int(item_id),),
        ).fetchone()
        if project is not None:
            value["project_id"] = int(project[0])
            value["item_title"] = str(project[1])
    if value.get("project_id") is None and value.get("deployment_run_id"):
        project = conn.execute(
            f"SELECT project_id FROM deployment_runs WHERE id = {p}",
            (str(value["deployment_run_id"]),),
        ).fetchone()
        if project is not None:
            value["project_id"] = int(project[0])
    if value.get("project_id") is None:
        raise ValueError(
            f"QA requirement {requirement_id} has no project authority"
        )
    return value


def ensure_qa_review_request(
    conn: Any,
    *,
    requirement_id: int,
    run_id: int,
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
) -> tuple[Optional[dict[str, Any]], bool]:
    """Create or reuse the review request for an inconclusive QA run."""
    required = ("decision_requests", "projects", "items")
    if not all(_table_exists(conn, table) for table in required):
        return None, False
    requirement = _requirement(conn, requirement_id)
    project_id = int(requirement["project_id"])
    return create_decision_request(
        conn,
        kind="qa_needs_review",
        subject_type="qa_requirement",
        subject_key=str(int(requirement_id)),
        project_id=project_id,
        originator_actor_id=originator_actor_id,
        role_authorities=[
            RoleAuthority("project", project_id, "owner"),
            RoleAuthority("project", project_id, "operator"),
        ],
        subject_context={
            "requirement_id": int(requirement_id),
            "run_id": int(run_id),
            "qa_kind": str(requirement["qa_kind"]),
            "plan_name": requirement.get("plan_name"),
            "title": "QA evidence needs your review",
            "evidence_summary": str(requirement.get("success_policy") or ""),
        },
        session_id=session_id,
    )


def maybe_ensure_qa_review_request(
    conn: Any,
    *,
    verdict: Optional[str],
    requirement_id: int,
    run_id: int,
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
) -> Optional[dict[str, Any]]:
    """Produce the review only for an inconclusive verdict."""
    if verdict != "inconclusive":
        return None
    request, _ = ensure_qa_review_request(
        conn,
        requirement_id=requirement_id,
        run_id=run_id,
        originator_actor_id=originator_actor_id,
        session_id=session_id,
    )
    return request


def apply_qa_review_resolution(
    conn: Any,
    *,
    requirement_id: int,
    action: str,
    actor_id: int,
    note: Optional[str],
    resolved_at: Optional[str] = None,
) -> None:
    """Apply the human decision to the canonical requirement evidence."""
    requirement = _requirement(conn, requirement_id)
    stamp = resolved_at or iso8601_now()
    p = _p(conn)
    if action == "waive":
        conn.execute(
            "UPDATE qa_requirements SET "
            f"waived_at = {p}, waiver_rationale = {p}, "
            f"waiver_source = {p} WHERE id = {p}",
            (
                stamp,
                (note or "Waived through Inbox review").strip(),
                f"actor:{actor_id}",
                int(requirement_id),
            ),
        )
        return
    verdict = "pass" if action == "approve" else "fail"
    conn.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, executor_type, qa_kind, verdict, raw_result, "
        "started_at, completed_at, created_at) "
        f"VALUES ({p}, 'human_review', {p}, {p}, {p}, {p}, {p}, {p})",
        (
            int(requirement_id),
            str(requirement["qa_kind"]),
            verdict,
            note,
            stamp,
            stamp,
            stamp,
        ),
    )


__all__ = [
    "apply_qa_review_resolution",
    "ensure_qa_review_request",
    "maybe_ensure_qa_review_request",
]

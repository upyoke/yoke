"""Decision-request producer and consumer for QA evidence review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    list_subject_requests,
)
from yoke_core.domain.schema_common import _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class QaReviewWait:
    """A blocking requirement whose evidence awaits an authorized person."""

    requirement_id: int
    request_id: int
    verdict_reason: str
    authorities: tuple[str, ...]

    @property
    def detail(self) -> str:
        reason = f": {self.verdict_reason}" if self.verdict_reason else ""
        return (
            f"Requirement #{self.requirement_id} awaits human evidence review "
            f"in decision request {self.request_id}{reason}"
        )

    @property
    def recovery(self) -> str:
        named = ", ".join(self.authorities) or "a resolver named by the request"
        return (
            f"Authorized resolver(s): {named}. Run `yoke decision-requests "
            f"resolve {self.request_id} approve|reject|waive --note "
            '"<evidence decision>"`.'
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "request_id": self.request_id,
            "verdict_reason": self.verdict_reason,
            "authorities": list(self.authorities),
            "detail": self.detail,
            "recovery": self.recovery,
        }


def requirement_awaits_human_review(
    conn: Any,
    requirement_id: int,
) -> Optional[QaReviewWait]:
    """Return the live QA-review blocker for one unsatisfied requirement."""
    required = (
        "qa_requirements",
        "qa_runs",
        "decision_requests",
        "decision_request_role_authorities",
        "decision_request_actor_authorities",
    )
    if not all(_table_exists(conn, table) for table in required):
        return None
    p = _p(conn)
    requirement = conn.execute(
        f"SELECT blocking_mode, waived_at FROM qa_requirements WHERE id = {p}",
        (int(requirement_id),),
    ).fetchone()
    if requirement is None:
        return None
    blocking_mode = (
        requirement["blocking_mode"] if hasattr(requirement, "keys") else requirement[0]
    )
    waived_at = (
        requirement["waived_at"] if hasattr(requirement, "keys") else requirement[1]
    )
    if str(blocking_mode) != "blocking" or waived_at:
        return None
    latest = conn.execute(
        "SELECT performed_by, verdict, verdict_reason FROM qa_runs "
        f"WHERE qa_requirement_id = {p} ORDER BY created_at DESC, id DESC LIMIT 1",
        (int(requirement_id),),
    ).fetchone()
    if latest is None:
        return None
    performed_by = latest["performed_by"] if hasattr(latest, "keys") else latest[0]
    verdict = latest["verdict"] if hasattr(latest, "keys") else latest[1]
    verdict_reason = latest["verdict_reason"] if hasattr(latest, "keys") else latest[2]
    if str(performed_by or "") != "agent" or str(verdict or "") != "undetermined":
        return None
    request = next(
        (
            row
            for row in list_subject_requests(
                conn, "qa_requirement", str(int(requirement_id))
            )
            if row["kind"] == "qa_needs_review" and row["status"] == "pending"
        ),
        None,
    )
    if request is None:
        return None
    labels = {
        f"{row['scope_kind']} {str(row['role_name']).replace('_', ' ')}"
        for row in request.get("role_authorities", [])
    }
    labels.update(f"actor {value}" for value in request.get("named_actor_ids", []))
    return QaReviewWait(
        requirement_id=int(requirement_id),
        request_id=int(request["id"]),
        verdict_reason=str(verdict_reason or "").strip(),
        authorities=tuple(sorted(labels)),
    )


def _requirement(conn: Any, requirement_id: int) -> dict[str, Any]:
    p = _p(conn)
    row = conn.execute(
        "SELECT id, item_id, epic_id, deployment_run_id, plan_id, "
        "plan_case_key, method_id, method_name, qa_kind, success_policy "
        "FROM qa_requirements "
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
    if (
        value.get("method_id") is not None
        and value.get("method_name") is None
        and value.get("plan_id") is None
    ):
        method = conn.execute(
            f"SELECT name FROM qa_methods WHERE id = {p}",
            (str(value["method_id"]),),
        ).fetchone()
        if method is not None:
            value["method_name"] = str(method[0])
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
        raise ValueError(f"QA requirement {requirement_id} has no project authority")
    return value


def ensure_qa_review_request(
    conn: Any,
    *,
    requirement_id: int,
    run_id: int,
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
    commit: bool = True,
) -> tuple[Optional[dict[str, Any]], bool]:
    """Create or reuse the review request for an undetermined QA run."""
    required = ("decision_requests", "projects", "items")
    if not all(_table_exists(conn, table) for table in required):
        return None, False
    requirement = _requirement(conn, requirement_id)
    project_id = int(requirement["project_id"])
    p = _p(conn)
    reason_row = conn.execute(
        f"SELECT verdict_reason FROM qa_runs WHERE id={p} AND qa_requirement_id={p}",
        (int(run_id), int(requirement_id)),
    ).fetchone()
    verdict_reason = str(reason_row[0] if reason_row else "").strip()
    if not verdict_reason:
        raise ValueError("undetermined QA run is missing its required reason")
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
            "plan_id": (
                int(requirement["plan_id"])
                if requirement.get("plan_id") is not None
                else None
            ),
            "qa_kind": str(requirement["qa_kind"]),
            "plan_name": requirement.get("plan_name"),
            "case_name": requirement.get("plan_case_key"),
            "method_name": requirement.get("method_name"),
            "title": "QA evidence needs your review",
            "evidence_summary": verdict_reason,
        },
        session_id=session_id,
        commit=commit,
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
    """Produce human work only for an agent's undetermined verdict."""
    if verdict != "undetermined":
        return None
    p = _p(conn)
    run = conn.execute(
        f"SELECT performed_by FROM qa_runs WHERE id={p} AND qa_requirement_id={p}",
        (int(run_id), int(requirement_id)),
    ).fetchone()
    performed_by = (
        run["performed_by"]
        if run is not None and hasattr(run, "keys")
        else run[0]
        if run is not None
        else None
    )
    if str(performed_by or "") != "agent":
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
        "(qa_requirement_id, performed_by, qa_kind, verdict, raw_result, "
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
    "QaReviewWait",
    "apply_qa_review_resolution",
    "ensure_qa_review_request",
    "maybe_ensure_qa_review_request",
    "requirement_awaits_human_review",
]

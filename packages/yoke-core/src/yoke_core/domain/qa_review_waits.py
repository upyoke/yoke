"""Which blocking QA requirements wait on a person's evidence review.

A requirement waits when its latest actual attempt is ``undetermined`` and a
pending ``qa_needs_review`` request names that attempt. The answer for a set
of requirements costs a fixed number of statements, whatever its size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_rows import request_rows
from yoke_core.domain.qa_latest_execution import latest_executions
from yoke_core.domain.schema_common import _table_exists


_REQUIRED_TABLES = (
    "qa_requirements",
    "qa_runs",
    "decision_requests",
    "decision_request_role_authorities",
    "decision_request_actor_authorities",
)


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


def _holes(conn: Any, values: tuple[Any, ...]) -> str:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    return ", ".join(marker for _ in values)


def requirements_awaiting_human_review(
    conn: Any, requirement_ids: Iterable[int]
) -> dict[int, QaReviewWait]:
    """The live QA-review blocker of each named requirement that has one."""
    ids = tuple(sorted({int(value) for value in requirement_ids}))
    if not ids or not all(_table_exists(conn, table) for table in _REQUIRED_TABLES):
        return {}
    rows = conn.execute(
        "SELECT id, blocking_mode, waived_at FROM qa_requirements "
        f"WHERE id IN ({_holes(conn, ids)})",
        ids,
    ).fetchall()
    blocking = [int(row[0]) for row in rows if str(row[1]) == "blocking" and not row[2]]
    undetermined = {
        requirement_id: run
        for requirement_id, run in latest_executions(conn, blocking).items()
        if run["verdict"] == "undetermined"
    }
    if not undetermined:
        return {}
    keys = tuple(str(requirement_id) for requirement_id in sorted(undetermined))
    pending = conn.execute(
        "SELECT id, subject_key FROM decision_requests "
        "WHERE subject_type = 'qa_requirement' AND kind = 'qa_needs_review' "
        f"AND status = 'pending' AND subject_key IN ({_holes(conn, keys)}) "
        "ORDER BY created_at DESC, id DESC",
        keys,
    ).fetchall()
    composed = request_rows(conn, (int(row[0]) for row in pending))
    waits: dict[int, QaReviewWait] = {}
    for row in pending:
        requirement_id = int(row[1])
        request = composed.get(int(row[0]))
        latest = undetermined[requirement_id]
        if requirement_id in waits or request is None:
            continue
        run_id = int((request.get("subject_context") or {}).get("run_id") or 0)
        if run_id != int(latest["id"]):
            continue
        labels = {
            f"{entry['scope_kind']} {str(entry['role_name']).replace('_', ' ')}"
            for entry in request.get("role_authorities", [])
        }
        labels.update(f"actor {value}" for value in request.get("named_actor_ids", []))
        waits[requirement_id] = QaReviewWait(
            requirement_id=requirement_id,
            request_id=int(request["id"]),
            verdict_reason=str(latest["verdict_reason"] or "").strip(),
            authorities=tuple(sorted(labels)),
        )
    return waits


def requirement_awaits_human_review(
    conn: Any, requirement_id: int
) -> Optional[QaReviewWait]:
    """The live QA-review blocker for one unsatisfied requirement."""
    return requirements_awaiting_human_review(conn, (requirement_id,)).get(
        int(requirement_id)
    )


__all__ = [
    "QaReviewWait",
    "requirement_awaits_human_review",
    "requirements_awaiting_human_review",
]

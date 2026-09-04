"""Durable observed state for one merge-queue landing pull request."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_landing_record_state import (
    CLOSED_UNMERGED,
    CONFLICTED,
    ENTRY_CHECKS_FAILED,
    LANDED,
    PENDING,
    STALLED,
)
from yoke_core.domain.session_message_types import row_dict
from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck


@dataclass(frozen=True)
class LandingRecord:
    """One server observation consumed by every waiter for this lane."""

    item_id: int
    project_id: int
    pr_number: str
    state: str
    head_sha: str = ""
    failed_checks: tuple[LandingCheck, ...] = field(default_factory=tuple)
    narrative: str = ""
    disarm_note: str = ""
    observed_at: str = ""
    changed_at: str = ""

    def with_disarm_note(self, note: str) -> "LandingRecord":
        return replace(self, disarm_note=str(note or ""))

    def payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "project_id": self.project_id,
            "pr_number": self.pr_number,
            "state": self.state,
            "head_sha": self.head_sha,
            "failed_checks": [_check_payload(check) for check in self.failed_checks],
            "narrative": self.narrative,
            "disarm_note": self.disarm_note,
            "observed_at": self.observed_at,
            "changed_at": self.changed_at,
        }


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _check_payload(check: LandingCheck) -> dict[str, Any]:
    return {
        "name": check.name,
        "status": check.status,
        "conclusion": check.conclusion,
        "required": check.required,
        "url": check.url,
    }


def _decode_checks(raw: Any) -> tuple[LandingCheck, ...]:
    parsed = json.loads(str(raw or "[]"))
    if not isinstance(parsed, list):
        raise ValueError("landing record failed_checks is not a JSON list")
    checks: list[LandingCheck] = []
    for value in parsed:
        if not isinstance(value, dict):
            raise ValueError("landing record failed_checks contains a non-object")
        checks.append(
            LandingCheck(
                name=str(value.get("name") or "unnamed check"),
                status=str(value.get("status") or ""),
                conclusion=str(value.get("conclusion") or ""),
                required=bool(value.get("required")),
                url=str(value.get("url") or ""),
            )
        )
    return tuple(checks)


def _narrative(readback: LandingReadback, pr_number: str) -> str:
    state = readback.state
    if state is None:
        reason = readback.state_error or "no reason given"
        return f"pull request {pr_number}: unreadable this observation ({reason})"
    if state.merged:
        return f"pull request {pr_number}: merged=true"
    return (
        f"pull request {pr_number}: merged=false, "
        f"state={'closed' if state.closed else 'open'}, {readback.describe()}"
    )


def from_readback(
    *,
    item_id: int,
    project_id: int,
    pr_number: str,
    readback: LandingReadback,
    observed_at: str,
) -> LandingRecord:
    """Classify the four server-read landing facts into a durable record."""
    state = readback.state
    kind = PENDING
    failed = readback.failed_required
    if state is not None and state.merged:
        kind = LANDED
    elif state is None:
        kind = PENDING
    elif readback.membership is None or readback.admitted():
        kind = PENDING
    elif failed:
        kind = ENTRY_CHECKS_FAILED
    elif state.closed:
        kind = CLOSED_UNMERGED
    elif (
        str(state.merge_state_status or "").strip().lower() == "dirty"
        or str(readback.membership.mergeable or "").strip().upper()
        == "CONFLICTING"
    ):
        kind = CONFLICTED
    else:
        kind = STALLED
    return LandingRecord(
        item_id=item_id,
        project_id=project_id,
        pr_number=pr_number,
        state=kind,
        head_sha=str(state.head_sha if state is not None else ""),
        failed_checks=failed,
        narrative=_narrative(readback, pr_number),
        observed_at=observed_at,
        changed_at=observed_at,
    )


def write_landing_record(conn: Any, record: LandingRecord) -> None:
    """Upsert one observation, preserving ``changed_at`` when facts match."""
    p = _p(conn)
    checks = json.dumps(
        [_check_payload(check) for check in record.failed_checks],
        sort_keys=True,
        separators=(",", ":"),
    )
    conn.execute(
        "INSERT INTO merge_queue_landing_records "
        "(item_id,project_id,pr_number,state,head_sha,failed_checks,narrative,"
        "disarm_note,observed_at,changed_at) "
        f"VALUES ({','.join([p] * 10)}) "
        "ON CONFLICT(item_id) DO UPDATE SET "
        "project_id=excluded.project_id, pr_number=excluded.pr_number, "
        "state=excluded.state, head_sha=excluded.head_sha, "
        "failed_checks=excluded.failed_checks, narrative=excluded.narrative, "
        "disarm_note=excluded.disarm_note, observed_at=excluded.observed_at, "
        "changed_at=CASE WHEN "
        "merge_queue_landing_records.pr_number<>excluded.pr_number OR "
        "merge_queue_landing_records.state<>excluded.state OR "
        "merge_queue_landing_records.head_sha<>excluded.head_sha OR "
        "merge_queue_landing_records.failed_checks<>excluded.failed_checks OR "
        "merge_queue_landing_records.narrative<>excluded.narrative OR "
        "merge_queue_landing_records.disarm_note<>excluded.disarm_note "
        "THEN excluded.changed_at ELSE merge_queue_landing_records.changed_at END",
        (
            record.item_id,
            record.project_id,
            record.pr_number,
            record.state,
            record.head_sha,
            checks,
            record.narrative,
            record.disarm_note,
            record.observed_at,
            record.changed_at,
        ),
    )


def read_landing_record(conn: Any, item_id: int) -> LandingRecord | None:
    p = _p(conn)
    row = conn.execute(
        "SELECT item_id,project_id,pr_number,state,head_sha,failed_checks,"
        "narrative,disarm_note,observed_at,changed_at "
        f"FROM merge_queue_landing_records WHERE item_id={p}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    value = row_dict(row)
    return LandingRecord(
        item_id=int(value["item_id"]),
        project_id=int(value["project_id"]),
        pr_number=str(value["pr_number"]),
        state=str(value["state"]),
        head_sha=str(value.get("head_sha") or ""),
        failed_checks=_decode_checks(value.get("failed_checks")),
        narrative=str(value.get("narrative") or ""),
        disarm_note=str(value.get("disarm_note") or ""),
        observed_at=str(value.get("observed_at") or ""),
        changed_at=str(value.get("changed_at") or ""),
    )


def delete_landing_record(conn: Any, item_id: int) -> None:
    p = _p(conn)
    conn.execute(
        f"DELETE FROM merge_queue_landing_records WHERE item_id={p}",
        (int(item_id),),
    )


def record_from_payload(payload: Any) -> LandingRecord | None:
    """Parse the registered function's record payload on the waiting client."""
    if not isinstance(payload, dict) or not payload:
        return None
    return LandingRecord(
        item_id=int(payload["item_id"]),
        project_id=int(payload["project_id"]),
        pr_number=str(payload["pr_number"]),
        state=str(payload["state"]),
        head_sha=str(payload.get("head_sha") or ""),
        failed_checks=_decode_checks(json.dumps(payload.get("failed_checks") or [])),
        narrative=str(payload.get("narrative") or ""),
        disarm_note=str(payload.get("disarm_note") or ""),
        observed_at=str(payload.get("observed_at") or ""),
        changed_at=str(payload.get("changed_at") or ""),
    )


__all__ = [
    "LandingRecord",
    "delete_landing_record",
    "from_readback",
    "read_landing_record",
    "record_from_payload",
    "write_landing_record",
]

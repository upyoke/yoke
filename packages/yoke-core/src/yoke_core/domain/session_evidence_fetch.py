"""Serve one machine-local evidence read through the owning machine's relay.

The control plane never holds these files. It holds the request, hands it to
the one relay whose machine wrote them, and stores the bounded answer that
comes back — so a seat anywhere reads a capture that exists in exactly one
place, without that place having to ship its logs anywhere.
"""

from __future__ import annotations

from datetime import timedelta
from time import monotonic, sleep
from typing import Any, Mapping
from uuid import uuid4

from yoke_contracts.session_control.evidence import (
    valid_native_diagnostic_reference,
)
from yoke_contracts.session_control.evidence_fetch import (
    EVIDENCE_REQUEST_TTL_SECONDS,
    EVIDENCE_WAIT_DEFAULT_SECONDS,
    evidence_pull_command,
)
from yoke_core.domain import json_helper
from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_WRITE,
    permission_decision,
)
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
)
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.session_relay_types import SessionRelayError


_RESULT_POLL_SECONDS = 0.25
_TERMINAL_STATES = ("succeeded", "failed", "expired")


def _live_row(
    conn: Any,
    *,
    session_id: str,
    kind: str | None,
    file_name: str | None,
    diagnostic_ref: str | None,
) -> Mapping[str, Any] | None:
    """Return an identical request already in flight, so a retry never doubles."""
    p = marker(conn)
    row = conn.execute(
        "SELECT * FROM session_evidence_fetches "
        f"WHERE target_session_id={p} AND state IN ('pending','leased') "
        f"AND COALESCE(kind,'')={p} AND COALESCE(file_name,'')={p} "
        f"AND COALESCE(diagnostic_ref,'')={p} "
        "ORDER BY requested_at DESC LIMIT 1",
        (session_id, kind or "", file_name or "", diagnostic_ref or ""),
    ).fetchone()
    return row_dict(row) if row is not None else None


def expire_stale_evidence_requests(conn: Any, *, now: str) -> None:
    """Release dead leases and retire requests nobody is waiting on any more."""
    p = marker(conn)
    current = parse_timestamp(now)
    if current is None:
        raise SessionRelayError(
            "clock_invalid", "evidence expiry time is not a readable timestamp"
        )
    conn.execute(
        "UPDATE session_evidence_fetches SET state='pending',lease_id=NULL,"
        f"lease_expires_at=NULL WHERE state='leased' AND lease_expires_at<={p}",
        (now,),
    )
    conn.execute(
        "UPDATE session_evidence_fetches SET state='expired',completed_at="
        + p
        + f",result_code='not_found' WHERE state='pending' AND requested_at<={p}",
        (
            now,
            timestamp(current - timedelta(seconds=EVIDENCE_REQUEST_TTL_SECONDS)),
        ),
    )


def request_evidence_fetch(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str | None,
    session_id: str,
    kind: str | None,
    file_name: str | None,
    evidence_id: str | None,
    tail_lines: int,
    now: str,
) -> dict[str, Any]:
    """Record one bounded read for the machine that owns the target session."""
    from yoke_core.domain.session_operator_authority import session_control_target

    target = session_control_target(conn, session_id)
    machine_id = str(target.get("machine_id") or "")
    if not machine_id:
        raise SessionRelayError(
            "machine_unknown",
            f"Session '{session_id}' records no machine, so no relay owns its "
            "files. Read them on the machine that ran it.",
        )
    project_id = int(target.get("project_id") or 0)
    if not permission_decision(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        permission_key=PERM_ITEMS_WRITE,
    ).allowed:
        raise SessionRelayError(
            "permission_denied",
            f"actor {actor_id} cannot read evidence for project {project_id}",
        )
    diagnostic_ref = None
    if evidence_id is not None:
        diagnostic_ref = valid_native_diagnostic_reference(evidence_id)
        if diagnostic_ref is None:
            raise SessionRelayError(
                "evidence_id_invalid",
                f"'{evidence_id}' is not a diagnostic reference; pass the "
                "`nd-` value the fleet report or attempt evidence named.",
            )
    expire_stale_evidence_requests(conn, now=now)
    existing = _live_row(
        conn,
        session_id=session_id,
        kind=kind,
        file_name=file_name,
        diagnostic_ref=diagnostic_ref,
    )
    if existing is not None:
        conn.commit()
        return dict(existing)
    fetch_id = str(uuid4())
    p = marker(conn)
    conn.execute(
        "INSERT INTO session_evidence_fetches (fetch_id,target_session_id,"
        "project_id,machine_id,kind,file_name,diagnostic_ref,tail_lines,state,"
        "requested_at,requested_by_actor_id,requested_by_session_id) VALUES ("
        + ",".join(p for _ in range(12))
        + ")",
        (
            fetch_id,
            session_id,
            project_id,
            machine_id,
            kind,
            file_name,
            diagnostic_ref,
            int(tail_lines),
            "pending",
            now,
            int(actor_id),
            caller_session_id,
        ),
    )
    conn.commit()
    return {
        "fetch_id": fetch_id,
        "target_session_id": session_id,
        "project_id": project_id,
        "machine_id": machine_id,
        "kind": kind,
        "file_name": file_name,
        "diagnostic_ref": diagnostic_ref,
        "tail_lines": int(tail_lines),
        "state": "pending",
    }


def read_evidence_fetch(conn: Any, fetch_id: str) -> dict[str, Any]:
    p = marker(conn)
    row = conn.execute(
        f"SELECT * FROM session_evidence_fetches WHERE fetch_id={p}",
        (fetch_id,),
    ).fetchone()
    if row is None:
        raise SessionRelayError("fetch_missing", "evidence request does not exist")
    return row_dict(row)


def evidence_fetch_result(record: Mapping[str, Any]) -> dict[str, Any]:
    """Shape one stored request as the answer its caller asked for."""
    state = str(record.get("state") or "")
    session_id = str(record.get("target_session_id") or "")
    try:
        files = json_helper.loads_text(str(record.get("files") or "[]"))
    except (TypeError, ValueError):
        files = []
    return {
        "fetch_id": str(record.get("fetch_id") or ""),
        "session_id": session_id,
        "machine_id": str(record.get("machine_id") or ""),
        "state": state,
        "result_code": str(record.get("result_code") or "") or None,
        "files": files if isinstance(files, list) else [],
        "selected_file": str(record.get("selected_file") or "") or None,
        "content": record.get("content"),
        "content_bytes": int(record.get("content_bytes") or 0),
        "truncated": bool(record.get("truncated")),
        "recovery": (
            None
            if state in _TERMINAL_STATES
            else evidence_pull_command(
                session_id,
                str(record.get("diagnostic_ref") or "") or None,
            )
        ),
    }


def wait_for_evidence_fetch(
    conn: Any,
    fetch_id: str,
    *,
    wait_seconds: float = EVIDENCE_WAIT_DEFAULT_SECONDS,
) -> dict[str, Any]:
    """Read the answer back without outliving the caller's dispatch timeout."""
    deadline = monotonic() + max(0.0, float(wait_seconds))
    while True:
        record = read_evidence_fetch(conn, fetch_id)
        if str(record.get("state") or "") in _TERMINAL_STATES:
            return evidence_fetch_result(record)
        remaining = deadline - monotonic()
        if remaining <= 0:
            return evidence_fetch_result(record)
        conn.commit()
        sleep(min(_RESULT_POLL_SECONDS, remaining))

__all__ = [
    "evidence_fetch_result",
    "expire_stale_evidence_requests",
    "read_evidence_fetch",
    "request_evidence_fetch",
    "wait_for_evidence_fetch",
]

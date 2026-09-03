"""Lease and settle one machine-local evidence read as a relay job.

The read runs on the machine that owns the files, so the control plane's
whole part is handing that machine an exact, bounded question and storing
the answer. This is the relay-facing half of the fetch; the caller-facing
half lives in :mod:`yoke_core.domain.session_evidence_fetch`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping, Sequence
from uuid import uuid4

from yoke_contracts.session_control.evidence import (
    valid_native_diagnostic_reference,
)
from yoke_contracts.session_control.evidence_fetch import (
    EVIDENCE_LEASE_SECONDS,
    EVIDENCE_MAX_BYTES,
    EVIDENCE_RESULT_CODES,
    evidence_result_succeeded,
)
from yoke_core.domain import json_helper
from yoke_core.domain.session_evidence_fetch import read_evidence_fetch
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
)
from yoke_core.domain.session_relay_storage import (
    clear_relay_batch_when_drained,
    mark_relay_batch,
    marker,
    require_relay_batch,
)
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    RelayJob,
    SessionRelayError,
)


#: How many of a session's own attempts are scanned for diagnostic references.
_DIAGNOSTIC_REF_LIMIT = 25
_TERMINAL_STATES = ("succeeded", "failed", "expired")


def _diagnostic_refs(conn: Any, session_id: str) -> tuple[str, ...]:
    """Return the diagnostic references this session's own attempts recorded.

    Captures on disk are keyed by an opaque reference, not by session, so the
    machine cannot answer "what do you hold for this session" on its own. The
    control plane can: every reference was reported to it by the attempt that
    produced it, and those attempts name the session.
    """
    p = marker(conn)
    rows = conn.execute(
        "SELECT evidence FROM session_message_attempts "
        f"WHERE target_session_id={p} AND evidence IS NOT NULL "
        "UNION ALL "
        "SELECT a.evidence FROM session_launch_attempts a "
        "JOIN session_launches l ON l.launch_id = a.launch_id "
        f"WHERE (l.registered_session_id={p} OR l.native_session_id={p}) "
        "AND a.evidence IS NOT NULL",
        (session_id, session_id, session_id),
    ).fetchall()
    found: list[str] = []
    for row in rows:
        try:
            document = json_helper.loads_text(str(row[0]))
        except (TypeError, ValueError):
            continue
        if not isinstance(document, Mapping):
            continue
        reference = valid_native_diagnostic_reference(
            document.get("native_diagnostic_ref")
        )
        if reference is not None and reference not in found:
            found.append(reference)
    return tuple(found[:_DIAGNOSTIC_REF_LIMIT])


def claim_evidence_fetch(
    conn: Any,
    heartbeat: RelayHeartbeat,
    *,
    now: str,
) -> RelayJob | None:
    """Lease this machine's oldest pending read; a seat is blocked on it."""
    projects = tuple(sorted({int(value) for value in heartbeat.project_ids}))
    if not projects:
        return None
    p = marker(conn)
    lock = " FOR UPDATE SKIP LOCKED" if p == "%s" else ""
    row = conn.execute(
        "SELECT * FROM session_evidence_fetches WHERE state='pending' "
        f"AND machine_id={p} AND project_id IN ("
        + ",".join(p for _ in projects)
        + ") ORDER BY requested_at,fetch_id LIMIT 1"
        + lock,
        (heartbeat.machine_id, *projects),
    ).fetchone()
    if row is None:
        return None
    selected = row_dict(row)
    fetch_id = str(selected["fetch_id"])
    lease_id = str(uuid4())
    current = parse_timestamp(now)
    if current is None:
        raise SessionRelayError("clock_invalid", "relay evidence lease time is invalid")
    expires_at = timestamp(current + timedelta(seconds=EVIDENCE_LEASE_SECONDS))
    cursor = conn.execute(
        "UPDATE session_evidence_fetches SET state='leased',lease_id="
        + p
        + ",lease_expires_at="
        + p
        + f" WHERE fetch_id={p} AND state='pending'",
        (lease_id, expires_at, fetch_id),
    )
    if cursor.rowcount != 1:
        return None
    session_id = str(selected["target_session_id"])
    reference = str(selected.get("diagnostic_ref") or "")
    mark_relay_batch(
        conn,
        relay_id=heartbeat.relay_id,
        batch_id=lease_id,
        expires_at=expires_at,
        now=now,
    )
    conn.commit()
    return RelayJob(
        job_kind="evidence",
        job_id=fetch_id,
        lease_id=lease_id,
        machine_id=heartbeat.machine_id,
        surface="",
        surface_version="",
        project_id=int(selected["project_id"]),
        native_instruction="",
        target_session_id=session_id,
        evidence_request={
            "kind": str(selected.get("kind") or "") or None,
            "file_name": str(selected.get("file_name") or "") or None,
            "tail_lines": int(selected["tail_lines"]),
            "max_bytes": EVIDENCE_MAX_BYTES,
            "diagnostic_refs": (
                [reference] if reference else list(_diagnostic_refs(conn, session_id))
            ),
        },
    )


def report_evidence_fetch(
    conn: Any,
    *,
    relay_id: str,
    fetch_id: str,
    lease_id: str,
    result_code: str,
    document: Mapping[str, Any] | None,
    now: str,
) -> dict[str, Any]:
    """Store the bounded listing and tail this machine read back."""
    if result_code not in EVIDENCE_RESULT_CODES:
        raise SessionRelayError("result_invalid", "unknown evidence result code")
    record = read_evidence_fetch(conn, fetch_id)
    if str(record.get("lease_id") or "") != lease_id:
        raise SessionRelayError("lease_mismatch", "evidence lease does not match")
    if str(record.get("state") or "") in _TERMINAL_STATES:
        if str(record.get("result_code") or "") == result_code:
            return {"fetch_id": fetch_id, "result_code": result_code}
        raise SessionRelayError("report_conflict", "evidence read was already reported")
    require_relay_batch(conn, relay_id=relay_id, now=now)
    source = document if isinstance(document, Mapping) else {}
    files: Sequence[Any] = source.get("files") or ()
    content = str(source.get("content") or "")[:EVIDENCE_MAX_BYTES]
    p = marker(conn)
    conn.execute(
        "UPDATE session_evidence_fetches SET state="
        + p
        + ",completed_at="
        + p
        + ",result_code="
        + p
        + ",files="
        + p
        + ",selected_file="
        + p
        + ",content="
        + p
        + ",content_bytes="
        + p
        + ",truncated="
        + p
        + f" WHERE fetch_id={p}",
        (
            "succeeded" if evidence_result_succeeded(result_code) else "failed",
            now,
            result_code,
            json_helper.dumps_compact(list(files)),
            str(source.get("selected_file") or "") or None,
            content,
            len(content.encode("utf-8")),
            1 if source.get("truncated") else 0,
            fetch_id,
        ),
    )
    clear_relay_batch_when_drained(conn, relay_id=relay_id, batch_id=lease_id)
    conn.commit()
    return {"fetch_id": fetch_id, "result_code": result_code}


__all__ = ["claim_evidence_fetch", "report_evidence_fetch"]

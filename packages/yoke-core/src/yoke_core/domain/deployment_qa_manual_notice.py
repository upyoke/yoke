"""Read and settle requirement-owned notices independently of release runs."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.session_message_store import cancel_messages
from yoke_core.domain.schema_common import _table_exists

MANUAL_WAIT_PREFIX = "deployment-qa-manual-wait:"


def manual_notice_rows(
    conn: Any, *, run_id: str, stage_name: str
) -> list[dict[str, Any]]:
    """Present a carried requirement's existing wake under its current run."""
    if not _table_exists(conn, "qa_requirements"):
        return []
    p = marker(conn)
    rows = conn.execute(
        "SELECT m.message_id, m.idempotency_key, m.created_at AS sent_at, "
        "COALESCE(r.session_id,'') AS session_id, "
        "CASE WHEN m.cancelled_at IS NOT NULL THEN 'cancelled' "
        "WHEN h.ended_at IS NOT NULL THEN 'ended' ELSE COALESCE(r.state,'') END AS state, "
        "COALESCE(r.wake_escalation,'') AS escalation, "
        "q.deployment_member_item_id AS member, COALESCE(q.wake_evidence,'') AS evidence "
        "FROM qa_requirements q JOIN session_messages m ON m.idempotency_key LIKE "
        f"{p} || CAST(q.id AS TEXT) || {p} "
        "LEFT JOIN session_message_recipients r ON r.message_id=m.message_id "
        "LEFT JOIN harness_sessions h ON h.session_id=r.session_id "
        f"WHERE q.deployment_run_id={p} AND q.deployment_stage={p} "
        "ORDER BY m.created_at DESC, m.message_id",
        (MANUAL_WAIT_PREFIX, ":%", run_id, stage_name),
    ).fetchall()
    found = []
    for row in rows:
        record = dict(row)
        digest = sha256(record.pop("evidence").encode("utf-8")).hexdigest()
        if not record["idempotency_key"].endswith(f":{digest}"):
            continue
        member = record.pop("member")
        record["idempotency_key"] = (
            f"deployment-qa-stage-wait:{run_id}:{stage_name}:{member}:manual"
        )
        found.append(record)
    return found


def withdraw_settled_manual_notices(
    conn: Any, *, item_id: int | None, reason: str, now: Any, run_id: str | None = None
) -> int:
    """A run ending does not settle its carried requirement; QA or item closure does."""
    if not _table_exists(conn, "qa_requirements"):
        return 0
    p = marker(conn)
    rows = conn.execute(
        "SELECT m.message_id FROM session_messages m JOIN qa_requirements q "
        f"ON m.idempotency_key LIKE {p} || CAST(q.id AS TEXT) || {p} "
        f"WHERE m.cancelled_at IS NULL AND (CAST({p} AS TEXT) IS NULL OR q.deployment_run_id={p}) "
        "AND (q.waived_at IS NOT NULL "
        "OR q.superseded_at IS NOT NULL OR q.retracted_at IS NOT NULL "
        "OR EXISTS (SELECT 1 FROM qa_runs qr WHERE qr.qa_requirement_id=q.id) "
        f"OR q.deployment_member_item_id={p})",
        (MANUAL_WAIT_PREFIX, ":%", run_id, run_id, item_id),
    ).fetchall()
    ids = [str(row[0]) for row in rows]
    if ids:
        cancel_messages(
            conn, message_ids=ids, actor_id=None, reason=reason, cancelled_at=now
        )
    return len(ids)

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
    """Read once per presentation; a carried notice follows its requirement."""
    from yoke_core.domain.deployment_qa_presentation_facts import presented_run_ids
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    runs = presented_run_ids(conn, run_id) or (run_id,)
    p = marker(conn)

    def read():
        if not _table_exists(conn, "qa_requirements") or not _table_exists(
            conn, "session_messages"
        ):
            return []
        requirements = conn.execute(
            "SELECT id, deployment_member_item_id AS member, "
            "COALESCE(wake_evidence,'') AS evidence, "
            "deployment_run_id AS run_id, deployment_stage AS stage "
            f"FROM qa_requirements WHERE deployment_run_id IN ({','.join([p] * len(runs))})",
            runs,
        ).fetchall()
        by_key = {
            f"{MANUAL_WAIT_PREFIX}{row['id']}:"
            f"{sha256(row['evidence'].encode('utf-8')).hexdigest()}": dict(row)
            for row in requirements
        }
        if not by_key:
            return []
        messages = conn.execute(
            "SELECT m.message_id, m.idempotency_key, m.created_at AS sent_at, "
            "COALESCE(r.session_id,'') AS session_id, "
            "CASE WHEN m.cancelled_at IS NOT NULL THEN 'cancelled' "
            "WHEN h.ended_at IS NOT NULL THEN 'ended' ELSE COALESCE(r.state,'') END AS state, "
            "COALESCE(r.wake_escalation,'') AS escalation "
            "FROM session_messages m "
            "LEFT JOIN session_message_recipients r ON r.message_id=m.message_id "
            "LEFT JOIN harness_sessions h ON h.session_id=r.session_id "
            f"WHERE m.idempotency_key IN ({','.join([p] * len(by_key))}) "
            "ORDER BY m.created_at DESC, m.message_id",
            tuple(by_key),
        ).fetchall()
        return [
            {**dict(row), **by_key[row['idempotency_key']]}
            for row in messages
        ]

    found = []
    for row in presentation_read(conn, ("qa_manual_notices", runs), read):
        record = dict(row)
        if record.pop("run_id") != run_id or record.pop("stage") != stage_name:
            continue
        record.pop("evidence")
        member, requirement = record.pop("member"), record.pop("id")
        record["idempotency_key"] = (
            f"deployment-qa-stage-wait:{run_id}:{stage_name}:{member}:manual:{requirement}"
        )
        found.append(record)
    return found


def withdraw_obsolete_manual_notices(
    conn: Any, *, requirement_id: int, current_key: str, now: Any
) -> None:
    """Changed ownership or evidence retires the old instruction before sending."""
    p = marker(conn)
    rows = conn.execute(
        f"SELECT message_id FROM session_messages WHERE idempotency_key LIKE {p} "
        f"AND idempotency_key <> {p} AND cancelled_at IS NULL",
        (f"{MANUAL_WAIT_PREFIX}{requirement_id}:%", current_key),
    ).fetchall()
    if rows:
        cancel_messages(
            conn,
            message_ids=[str(row[0]) for row in rows],
            actor_id=None,
            reason="Manual QA owner or evidence changed",
            cancelled_at=now,
        )


def withdraw_settled_manual_notices(
    conn: Any,
    *,
    item_id: int | None,
    reason: str,
    now: Any,
    run_id: str | None = None,
) -> int:
    """A run ending does not settle its carried requirement; QA or item closure does."""
    if not _table_exists(conn, "qa_requirements") or not _table_exists(
        conn, "session_messages"
    ):
        return 0
    p = marker(conn)
    notices = conn.execute(
        "SELECT message_id, idempotency_key FROM session_messages "
        f"WHERE idempotency_key LIKE {p} AND cancelled_at IS NULL",
        (f"{MANUAL_WAIT_PREFIX}%",),
    ).fetchall()
    by_requirement: dict[int, list[str]] = {}
    for row in notices:
        requirement, separator, _suffix = str(row[1])[
            len(MANUAL_WAIT_PREFIX) :
        ].partition(":")
        if separator and requirement.isascii() and requirement.isdecimal():
            by_requirement.setdefault(int(requirement), []).append(str(row[0]))
    if not by_requirement:
        return 0
    item_clause = f" OR q.deployment_member_item_id={p}" if item_id is not None else ""
    rows = conn.execute(
        "SELECT q.id FROM qa_requirements q "
        f"WHERE q.id IN ({','.join([p] * len(by_requirement))}) "
        f"AND (CAST({p} AS TEXT) IS NULL OR q.deployment_run_id={p}) "
        "AND (q.waived_at IS NOT NULL OR q.superseded_at IS NOT NULL OR q.retracted_at IS NOT NULL "
        "OR EXISTS (SELECT 1 FROM qa_runs qr WHERE qr.qa_requirement_id=q.id) "
        + item_clause
        + ")",
        (*by_requirement, run_id, run_id, *((item_id,) if item_id is not None else ())),
    ).fetchall()
    ids = [message for row in rows for message in by_requirement[int(row[0])]]
    if ids:
        cancel_messages(
            conn, message_ids=ids, actor_id=None, reason=reason, cancelled_at=now
        )
    return len(ids)

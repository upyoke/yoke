"""A manual-wake QA owner parks only while it holds a scheduled recheck.

The stage driver sends one manual-wake notice per open requirement
(:mod:`deployment_qa_manual_wake`). Once that notice reached a session that
still holds the member's work claim, and the requirement's run is executing
that requirement's stage, the session's park must carry its own timed recheck
(:mod:`session_scheduled_wake`): nothing else wakes it when the evidence
appears. Parks before the stage opens (deploy waits, merge-time release
waits) owe nothing here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_contracts.qa_case_wake_path import MANUAL
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_manual_notice import MANUAL_WAIT_PREFIX
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_work_claim_sql import scope_int_sql
from yoke_core.domain.session_scheduled_wake import pending_session_wake_holders

_TABLES = (
    "session_messages",
    "qa_requirements",
    "qa_runs",
    "deployment_runs",
    "work_claims",
)


def _noticed_requirements(conn: Any, session_id: str) -> list[int]:
    """Requirement ids of live manual-wake notices addressed to this session."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        f"SELECT idempotency_key FROM session_messages WHERE idempotency_key LIKE {p} "
        "AND cancelled_at IS NULL",
        (f"{MANUAL_WAIT_PREFIX}%:{session_id}:%",),
    ).fetchall()
    found: set[int] = set()
    for row in rows:
        requirement, _, rest = str(row[0])[len(MANUAL_WAIT_PREFIX) :].partition(":")
        holder, _, _digest = rest.rpartition(":")
        if holder == session_id and requirement.isascii() and requirement.isdecimal():
            found.add(int(requirement))
    return sorted(found)


def open_manual_obligation(conn: Any, session_id: str) -> dict[str, Any] | None:
    """The first open, opened-stage manual requirement this holder was woken for."""
    if not session_id or not all(_table_exists(conn, table) for table in _TABLES):
        return None
    requirements = _noticed_requirements(conn, session_id)
    if not requirements:
        return None
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    row = conn.execute(
        "SELECT q.id, q.deployment_member_item_id, q.deployment_run_id, "
        "q.deployment_stage FROM qa_requirements q "
        "JOIN deployment_runs r ON r.id=q.deployment_run_id "
        f"WHERE q.id IN ({','.join([p] * len(requirements))}) "
        f"AND q.wake_path={p} AND q.waived_at IS NULL "
        "AND q.superseded_at IS NULL AND q.retracted_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs qr WHERE qr.qa_requirement_id=q.id) "
        "AND r.status='executing' AND r.current_stage=q.deployment_stage "
        "AND EXISTS (SELECT 1 FROM work_claims wc WHERE wc.released_at IS NULL "
        f"AND wc.target_kind='item' AND wc.session_id={p} "
        f"AND {item_scope}=q.deployment_member_item_id) "
        "ORDER BY q.id LIMIT 1",
        (*requirements, MANUAL, session_id),
    ).fetchone()
    if row is None:
        return None
    values = tuple(row)
    return {
        "requirement_id": int(values[0]),
        "item_id": int(values[1]),
        "run_id": str(values[2]),
        "stage": str(values[3]),
    }


def park_recheck_refusal(
    conn: Any, session_id: str, *, now: datetime | None = None
) -> str:
    """Why this session cannot park yet, or ``""`` when it may."""
    obligation = open_manual_obligation(conn, session_id)
    if obligation is None:
        return ""
    current = parse_instant(now or utc_now())
    if session_id in pending_session_wake_holders(conn, (session_id,), now=current):
        return ""
    from yoke_core.domain.project_identity import render_item_ref

    item_ref = render_item_ref(conn, obligation["item_id"])
    requirement = obligation["requirement_id"]
    return (
        f"This session was woken for manual-wake QA requirement #{requirement} "
        f"({item_ref}, run {obligation['run_id']} stage {obligation['stage']!r}) "
        "and holds no future scheduled recheck, so nothing would wake it when the "
        "evidence appears. Schedule your next recheck for whenever the evidence "
        "could plausibly exist, then park again: `yoke sessions wake schedule "
        f'--at UTC_INSTANT --reason "recheck evidence for {item_ref} requirement '
        f'#{requirement}"`.'
    )


__all__ = ["open_manual_obligation", "park_recheck_refusal"]

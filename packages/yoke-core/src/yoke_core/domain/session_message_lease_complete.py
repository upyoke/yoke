"""Settle one hook lease's still-current receipts, per message when known."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from yoke_contracts.session_control.wake_delivery import (
    HOOK_DEFERRED_FOR_BUDGET_RESULT,
    HOOK_INJECTED_RESULT,
    INLINE_OVERFLOW_RESULT,
    inline_overflow_skip_reason,
)
from yoke_core.domain.session_message_types import row_dict, timestamp


HOOK_RESULT_CODES = frozenset(
    {
        "dropped_by_sibling_denial",
        "empty_lease",
        HOOK_INJECTED_RESULT,
        INLINE_OVERFLOW_RESULT,
        HOOK_DEFERRED_FOR_BUDGET_RESULT,
        "render_output_missing",
    }
)


def _complete_launches(conn: Any, rows: list[dict[str, Any]], *, now: datetime) -> None:
    from yoke_core.domain.session_launch_registration import (
        complete_launch_for_message,
    )

    for row in rows:
        complete_launch_for_message(
            conn,
            message_id=str(row["message_id"]),
            session_id=str(row["target_session_id"]),
            now=timestamp(now),
            commit=False,
        )


def _merged_evidence(raw: Any, extra: Mapping[str, Any]) -> str:
    try:
        document = json.loads(raw) if raw else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        document = {}
    if not isinstance(document, dict):
        document = {}
    document.update(extra)
    return json.dumps(document, sort_keys=True)


def complete_hook_lease(
    conn: Any,
    *,
    lease_id: str,
    injected: bool,
    result: str,
    message_results: Mapping[str, str] | None = None,
) -> int:
    """Settle only the still-current recipients named by a hook lease."""
    from yoke_core.domain.session_message_delivery import (
        _begin_mutation,
        _expire_rows,
        _p,
        utc_now,
    )

    current = utc_now()
    stamp = timestamp(current)
    marker = _p(conn)
    completed: list[dict[str, Any]] = []
    per_message = dict(message_results or {})
    _begin_mutation(conn)
    try:
        _expire_rows(conn, now=current)
        lock = " FOR UPDATE OF r" if _postgres(conn) else ""
        rows = conn.execute(
            "SELECT a.attempt_id,a.message_id,a.target_session_id,"
            "r.injection_lease_id,r.state,a.evidence FROM session_message_attempts a "
            "JOIN session_message_recipients r ON r.message_id=a.message_id "
            "AND r.session_id=a.target_session_id WHERE a.lease_id="
            + marker
            + " AND a.attempt_kind='hook' AND a.completed_at IS NULL"
            + lock,
            (lease_id,),
        ).fetchall()
        for raw in rows:
            row = row_dict(raw)
            current_lease = str(row.get("injection_lease_id") or "")
            message_id = str(row["message_id"])
            injected_this, result_code = _row_result(
                current_lease=current_lease,
                lease_id=lease_id,
                message_id=message_id,
                injected=injected,
                result=result,
                per_message=per_message,
            )
            extra: dict[str, str] = {}
            if result_code == INLINE_OVERFLOW_RESULT:
                extra["skip_reason"] = inline_overflow_skip_reason(message_id)
            if extra:
                conn.execute(
                    "UPDATE session_message_attempts SET completed_at="
                    + marker
                    + ", result_code="
                    + marker
                    + ", evidence="
                    + marker
                    + " WHERE attempt_id="
                    + marker,
                    (
                        stamp,
                        result_code,
                        _merged_evidence(row.get("evidence"), extra),
                        row["attempt_id"],
                    ),
                )
            else:
                conn.execute(
                    "UPDATE session_message_attempts SET completed_at="
                    + marker
                    + ", result_code="
                    + marker
                    + " WHERE attempt_id="
                    + marker,
                    (stamp, result_code, row["attempt_id"]),
                )
            if current_lease != lease_id:
                continue
            if injected_this:
                conn.execute(
                    "UPDATE session_message_recipients SET state='injected', "
                    "injection_count=injection_count+1,last_injected_at="
                    + marker
                    + ",wake_after="
                    + marker
                    + ",injection_lease_id=NULL,injection_leased_at=NULL,"
                    "injection_lease_expires_at=NULL WHERE message_id="
                    + marker
                    + " AND session_id="
                    + marker
                    + " AND state IN ('pending','injected')",
                    (stamp, stamp, message_id, row["target_session_id"]),
                )
                completed.append(row)
            else:
                conn.execute(
                    "UPDATE session_message_recipients SET injection_lease_id=NULL,"
                    "injection_leased_at=NULL,injection_lease_expires_at=NULL "
                    "WHERE message_id="
                    + marker
                    + " AND session_id="
                    + marker
                    + " AND injection_lease_id="
                    + marker,
                    (message_id, row["target_session_id"], lease_id),
                )
        if completed:
            _complete_launches(conn, completed, now=current)
        conn.commit()
        return len(completed) if injected or completed else len(rows)
    except Exception:
        conn.rollback()
        raise


def _postgres(conn: Any) -> bool:
    from yoke_core.domain import db_backend

    return db_backend.connection_is_postgres(conn)


def _row_result(
    *,
    current_lease: str,
    lease_id: str,
    message_id: str,
    injected: bool,
    result: str,
    per_message: Mapping[str, str],
) -> tuple[bool, str]:
    if current_lease != lease_id:
        return False, "stale_lease_completion"
    if per_message:
        result_code = per_message.get(message_id, HOOK_DEFERRED_FOR_BUDGET_RESULT)
        if result_code not in HOOK_RESULT_CODES:
            return False, "hook_result_unknown"
        return result_code == HOOK_INJECTED_RESULT, result_code
    if result in HOOK_RESULT_CODES:
        return injected, result
    return False, "hook_result_unknown"


__all__ = ["HOOK_RESULT_CODES", "complete_hook_lease"]

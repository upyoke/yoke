"""Durable session facts used by recovery instead of disposable telemetry.

Prompt and completed-work markers survive pruning of individual calls.
The newest relay-observed turn end retains bounded provider evidence.
Automatic-resume attempts are reserved before waking and keyed to the last
real tool activity; only progress starts a fresh budget. Stop holds are
counted per session and item with their own cooldown instant.

Writers introspect minimal fixture schemas before writing. Native database
instants and canonical owned observation fields retain microseconds;
changing existing storage requires the governed migration, including the
timestamp-derived resume key so formatting cannot refund spent attempts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.db_helpers import instant_parameter

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns

#: Additive ``harness_sessions`` columns, in the order the schema applies
#: them. Both the fresh-install DDL and the converge step read this list,
#: so a new fact is declared once.
SESSION_RECOVERY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("first_user_prompt_at", "TIMESTAMPTZ DEFAULT NULL"),
    ("first_completed_work_at", "TIMESTAMPTZ DEFAULT NULL"),
    ("last_completed_work_at", "TIMESTAMPTZ DEFAULT NULL"),
    ("native_turn_end_recorded_at", "TIMESTAMPTZ DEFAULT NULL"),
    ("native_turn_end_observation", "TEXT DEFAULT NULL"),
    ("vendor_resume_episode_key", "TEXT DEFAULT NULL"),
    ("vendor_resume_attempts", "INTEGER NOT NULL DEFAULT 0"),
)

#: The compact session-and-item hold ledger the Stop gate reads.
PROMISED_WORK_HOLDS_TABLE = "session_promised_work_holds"

#: Bounded size for the stored provider message and error body. The
#: observation exists to classify a failure and explain it to a person,
#: and neither needs an unbounded provider payload on a session row.
OBSERVATION_MAX_CHARS = 4096


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _columns(conn: Any, table: str) -> set:
    try:
        return set(_schema_get_columns(conn, table))
    except db_backend.operational_error_types():
        return set()


def recovery_columns_present(conn: Any) -> bool:
    """True when ``harness_sessions`` carries these facts."""
    present = _columns(conn, "harness_sessions")
    return all(column in present for column, _ddl in SESSION_RECOVERY_COLUMNS)


def promised_work_holds_table_present(conn: Any) -> bool:
    """True when the Stop gate's hold ledger exists on this database."""
    return bool(_columns(conn, PROMISED_WORK_HOLDS_TABLE))


def stamp_first_user_prompt(conn: Any, session_id: str, at: datetime | str) -> None:
    """Record that this session's operator has now sent a prompt.

    Write-once: a later prompt must not move the stamp, because the fact
    is *when the conversation began*, and a probe is defined by never
    having one at all.
    """
    if not session_id or not recovery_columns_present(conn):
        return
    p = _p(conn)
    conn.execute(
        "UPDATE harness_sessions SET first_user_prompt_at = "
        f"COALESCE(first_user_prompt_at, {p}) WHERE session_id = {p}",
        (instant_parameter(conn, parse_instant(at)), session_id),
    )


def stamp_completed_work(conn: Any, session_id: str, at: datetime | str) -> None:
    """Record that a tool call completed for this session.

    ``first_completed_work_at`` is write-once and
    ``last_completed_work_at`` is monotonic, so a replayed observation
    that arrives out of order can neither invent earlier work nor undo
    later work.
    """
    if not session_id or not recovery_columns_present(conn):
        return
    at = instant_parameter(conn, parse_instant(at))
    p = _p(conn)
    conn.execute(
        "UPDATE harness_sessions SET "
        f"first_completed_work_at = COALESCE(first_completed_work_at, {p}), "
        "last_completed_work_at = CASE WHEN last_completed_work_at IS NULL "
        f"OR last_completed_work_at < {p} THEN {p} "
        "ELSE last_completed_work_at END "
        f"WHERE session_id = {p}",
        (at, at, at, session_id),
    )


def record_native_turn_end(
    conn: Any,
    session_id: str,
    *,
    observation: Mapping[str, Any],
    recorded_at: datetime | str,
) -> None:
    """Store the newest native turn-end observation on the session.

    Ordered by ``recorded_at`` so a late-arriving older report cannot
    replace a newer one — the relay reports per poll and two polls can
    overlap.
    """
    if not session_id or not recovery_columns_present(conn):
        return
    recorded_at = instant_parameter(conn, parse_instant(recorded_at))
    owned = dict(observation)
    if owned.get("observed_at") is not None:
        owned["observed_at"] = format_instant(owned["observed_at"])
    body = json_helper.dumps_compact(owned)[:OBSERVATION_MAX_CHARS]
    p = _p(conn)
    conn.execute(
        "UPDATE harness_sessions SET "
        f"native_turn_end_recorded_at = {p}, native_turn_end_observation = {p} "
        f"WHERE session_id = {p} AND (native_turn_end_recorded_at IS NULL "
        f"OR native_turn_end_recorded_at < {p})",
        (recorded_at, body, session_id, recorded_at),
    )


def native_turn_end(row: Mapping[str, Any]) -> dict[str, Any]:
    """The stored observation for one session row, or an empty mapping.

    A row whose stored body will not parse is not evidence, so it yields
    nothing rather than raising: one malformed row must not stop every
    other session on the machine from being recovered.
    """
    recorded_at = row.get("native_turn_end_recorded_at")
    if recorded_at is None:
        return {}
    raw = row.get("native_turn_end_observation")
    stored: Any = raw
    if isinstance(raw, str):
        try:
            stored = json_helper.loads_text(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(stored, Mapping):
        return {}
    return {**dict(stored), "recorded_at": parse_instant(recorded_at)}


def resume_episode_key(last_tool_call_at: datetime | str | None) -> str:
    """The budget episode a session is currently in.

    The session's own last tool call, because that is the only stamp that
    moves when the session gets something done. A resume that produced
    real work pushes it forward and starts a fresh episode; a provider
    that refuses again changes nothing and the attempt counts against the
    same budget.
    """
    return format_instant(last_tool_call_at) if last_tool_call_at is not None else ""


def reserve_resume_attempt(
    conn: Any,
    session_id: str,
    *,
    episode_key: str,
    budget: int,
) -> Optional[int]:
    """Claim one resume attempt, or report that the budget is spent.

    Returns the attempt number just reserved, or ``None`` when this
    episode has already spent ``budget`` attempts. One statement does the
    read and the write, so two pollers racing on the same session cannot
    both reserve the last attempt, and a caller that dies after
    reserving has already spent it — the failure mode that matters is a
    refunded attempt looping against a provider wall, not a lost one.
    """
    if not session_id or budget < 1 or not recovery_columns_present(conn):
        return None
    p = _p(conn)
    cursor = conn.execute(
        "UPDATE harness_sessions SET "
        f"vendor_resume_episode_key = {p}, "
        "vendor_resume_attempts = CASE "
        f"WHEN vendor_resume_episode_key = {p} "
        "THEN COALESCE(vendor_resume_attempts, 0) + 1 ELSE 1 END "
        f"WHERE session_id = {p} "
        f"AND (vendor_resume_episode_key IS NULL OR vendor_resume_episode_key <> {p} "
        f"OR COALESCE(vendor_resume_attempts, 0) < {p}) "
        "RETURNING vendor_resume_attempts",
        (episode_key, episode_key, session_id, episode_key, budget),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    value = row[0] if not isinstance(row, Mapping) else row["vendor_resume_attempts"]
    return int(value)


def release_resume_attempt(
    conn: Any,
    session_id: str,
    *,
    episode_key: str,
) -> None:
    """Give back an attempt the wake path refused outright.

    Reserving before the wake is what makes a crash between reserving and
    waking spend the attempt, which is the conservative answer when
    nobody can say whether the session was reached. A *named* refusal is
    not that case: the wake path reported by name that it sent nothing,
    so the attempt was never made and charging for it would burn the
    budget on a queue that was merely busy.

    Scoped to the episode it was reserved in, so a release arriving after
    the session did real work cannot decrement the new episode's count.
    """
    if not session_id or not recovery_columns_present(conn):
        return
    p = _p(conn)
    conn.execute(
        "UPDATE harness_sessions "
        "SET vendor_resume_attempts = COALESCE(vendor_resume_attempts, 0) - 1 "
        f"WHERE session_id = {p} AND vendor_resume_episode_key = {p} "
        "AND COALESCE(vendor_resume_attempts, 0) > 0",
        (session_id, episode_key),
    )


def resume_attempts_spent(row: Mapping[str, Any], *, episode_key: str) -> int:
    """Attempts already spent in this session's current episode.

    An older episode's counter reads as zero rather than carrying over,
    because the work that ended that episode is exactly what refunds the
    budget.
    """
    stored = str(row.get("vendor_resume_episode_key") or "")
    if stored != episode_key:
        return 0
    return int(row.get("vendor_resume_attempts") or 0)


def record_promised_work_hold(
    conn: Any, *, session_id: str, item_id: Any, at: datetime | str
) -> None:
    """Count one Stop hold against this session and item."""
    if not session_id or item_id is None:
        return
    if not promised_work_holds_table_present(conn):
        return
    p = _p(conn)
    conn.execute(
        f"INSERT INTO {PROMISED_WORK_HOLDS_TABLE} "
        "(session_id, item_id, hold_count, last_hold_at) "
        f"VALUES ({p}, {p}, 1, {p}) "
        "ON CONFLICT(session_id, item_id) DO UPDATE SET "
        f"hold_count = {PROMISED_WORK_HOLDS_TABLE}.hold_count + 1, "
        "last_hold_at = EXCLUDED.last_hold_at",
        (session_id, int(item_id), instant_parameter(conn, parse_instant(at))),
    )


def promised_work_holds(
    conn: Any, *, session_id: str, item_id: Any
) -> tuple[datetime | None, int]:
    """``(last_hold_at, hold_count)`` for one session and item."""
    if not session_id or item_id is None:
        return None, 0
    if not promised_work_holds_table_present(conn):
        return None, 0
    p = _p(conn)
    row = conn.execute(
        f"SELECT last_hold_at, hold_count FROM {PROMISED_WORK_HOLDS_TABLE} "
        f"WHERE session_id = {p} AND item_id = {p}",
        (session_id, int(item_id)),
    ).fetchone()
    if row is None:
        return None, 0
    entry = (
        row
        if isinstance(row, Mapping)
        else {"last_hold_at": row[0], "hold_count": row[1]}
    )
    stamped = (
        parse_instant(entry["last_hold_at"])
        if entry["last_hold_at"] is not None
        else None
    )
    return stamped, int(entry["hold_count"] or 0)


__all__ = [
    "OBSERVATION_MAX_CHARS",
    "PROMISED_WORK_HOLDS_TABLE",
    "SESSION_RECOVERY_COLUMNS",
    "native_turn_end",
    "promised_work_holds",
    "promised_work_holds_table_present",
    "record_native_turn_end",
    "record_promised_work_hold",
    "recovery_columns_present",
    "release_resume_attempt",
    "reserve_resume_attempt",
    "resume_attempts_spent",
    "resume_episode_key",
    "stamp_completed_work",
    "stamp_first_user_prompt",
]

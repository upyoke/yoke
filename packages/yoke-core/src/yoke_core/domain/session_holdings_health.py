"""Held-item health the session-card Currently held box paints from.

The fleet report already answers whether a holder is working, quiet, idle,
or in an act-now state. The card must not invent a second set of thresholds:
this module classifies from those same policy minutes and detectors, and the
roster projects one closed tone per session. The browser only paints it.

Worst-of across currently held items; parked sessions stay calm (never
orange/yellow from quiet or a blocked flag) unless an act-now flag is red.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from yoke_contracts.project_contract.project_keys import (
    DEFAULT_STEERING_REPORT_IDLE_MINUTES,
    DEFAULT_STEERING_REPORT_STAFFING_MINUTES,
)
from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.project_policy_capabilities import project_policy_value
from yoke_core.domain.qa_constants import VALID_VERDICTS
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.session_mode import session_is_parked
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, parse_stamp
from yoke_core.domain.work_claim_targets import scope_int_sql

from yoke_core.domain import db_backend


HOLDINGS_HEALTH_GREEN = "green"
HOLDINGS_HEALTH_YELLOW = "yellow"
HOLDINGS_HEALTH_ORANGE = "orange"
HOLDINGS_HEALTH_RED = "red"
HOLDINGS_HEALTH_TONES = (
    HOLDINGS_HEALTH_GREEN,
    HOLDINGS_HEALTH_YELLOW,
    HOLDINGS_HEALTH_ORANGE,
    HOLDINGS_HEALTH_RED,
)
_FAIL_VERDICTS = tuple(
    verdict for verdict in VALID_VERDICTS if verdict in {"fail", "error"}
)
_RANK = {
    HOLDINGS_HEALTH_GREEN: 0,
    HOLDINGS_HEALTH_YELLOW: 1,
    HOLDINGS_HEALTH_ORANGE: 2,
    HOLDINGS_HEALTH_RED: 3,
}


def _worse(left: str, right: str) -> str:
    return left if _RANK[left] >= _RANK[right] else right


def classify_current_holdings_health(
    *,
    parked: bool,
    idle_seconds: int,
    staffing_after_seconds: int,
    idle_after_seconds: int,
    stale_eligible: bool,
    item_blocked: bool,
    landed_open: bool,
    qa_failed: bool,
) -> str:
    """Return the closed tone the Currently held box should paint.

    Thresholds are the fleet report's staffing and idle windows, not a
    second client-side clock. Red is act-now; orange is idle-alarm or a
    blocked item; yellow is quiet past staffing and still below idle.
    """
    tone = HOLDINGS_HEALTH_GREEN
    if stale_eligible or landed_open or qa_failed:
        tone = HOLDINGS_HEALTH_RED
    if parked:
        return tone if tone == HOLDINGS_HEALTH_RED else HOLDINGS_HEALTH_GREEN
    if item_blocked:
        tone = _worse(tone, HOLDINGS_HEALTH_ORANGE)
    if idle_seconds >= int(idle_after_seconds):
        tone = _worse(tone, HOLDINGS_HEALTH_ORANGE)
    elif idle_seconds >= int(staffing_after_seconds):
        tone = _worse(tone, HOLDINGS_HEALTH_YELLOW)
    return tone


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _stamp(now: datetime | None) -> str:
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _session_ids(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(row.get("session_id") or "") for row in rows if row.get("session_id")
        )
    )


def _policy_minutes(conn: Any, project_id: int | None, key: str, default: int) -> int:
    try:
        return max(1, int(project_policy_value(conn, project_id, key, default)))
    except (TypeError, ValueError):
        return default
    except db_backend.database_error_types(conn):
        return default


def _policy_seconds(conn: Any, project_id: Any) -> tuple[int, int]:
    try:
        pid = int(project_id) if project_id is not None else None
    except (TypeError, ValueError):
        pid = None
    staffing = 60 * _policy_minutes(
        conn,
        pid,
        "steering_report_staffing_minutes",
        DEFAULT_STEERING_REPORT_STAFFING_MINUTES,
    )
    idle = 60 * _policy_minutes(
        conn,
        pid,
        "steering_report_idle_minutes",
        DEFAULT_STEERING_REPORT_IDLE_MINUTES,
    )
    return staffing, idle


def _claimed_item_rows(
    conn: Any,
    session_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not session_ids or not _table_exists(conn, "work_claims"):
        return []
    if not _table_exists(conn, "items"):
        return []
    marker = _marker(conn)
    item_id = scope_int_sql(conn, "c.scope", "item_id")
    blocked = (
        "i.blocked AS blocked"
        if _column_exists(conn, "items", "blocked")
        else "0 AS blocked"
    )
    merged = (
        "i.merged_at AS merged_at"
        if _column_exists(conn, "items", "merged_at")
        else "NULL AS merged_at"
    )
    landed = (
        "i.merge_queue_landed_at AS merge_queue_landed_at"
        if _column_exists(conn, "items", "merge_queue_landed_at")
        else "NULL AS merge_queue_landed_at"
    )
    try:
        rows = conn.execute(
            f"SELECT c.session_id AS session_id, {item_id} AS item_id, "
            "c.claimed_at AS claimed_at, i.status AS status, "
            f"{blocked}, {merged}, {landed} "
            f"FROM work_claims c JOIN items i ON i.id = {item_id} "
            "WHERE c.released_at IS NULL AND c.target_kind = 'item' "
            "AND c.session_id IN ("
            + ",".join(marker for _ in session_ids)
            + ")",
            tuple(session_ids),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return []
    return [dict(row) for row in rows]


def _qa_failed_item_ids(conn: Any, item_ids: Sequence[int]) -> set[int]:
    if not item_ids or not _table_exists(conn, "qa_requirements"):
        return set()
    if not _table_exists(conn, "qa_runs"):
        return set()
    marker = _marker(conn)
    fail_markers = ",".join(marker for _ in _FAIL_VERDICTS)
    try:
        ranked = conn.execute(
            "SELECT item_id FROM ("
            "SELECT q.item_id AS item_id, r.verdict AS verdict, "
            "ROW_NUMBER() OVER (PARTITION BY q.item_id "
            "ORDER BY r.id DESC) AS row_num "
            "FROM qa_requirements q JOIN qa_runs r "
            "ON r.qa_requirement_id = q.id WHERE q.item_id IN ("
            + ",".join(marker for _ in item_ids)
            + ")) latest WHERE row_num = 1 AND verdict IN ("
            + fail_markers
            + ")",
            (*tuple(int(value) for value in item_ids), *_FAIL_VERDICTS),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return set()
    return {int(row["item_id"]) for row in ranked}


def _landed_open(row: Mapping[str, Any]) -> bool:
    if str(row.get("status") or "") in TERMINAL_STATUSES:
        return False
    return bool(row.get("merged_at") or row.get("merge_queue_landed_at"))


def _stale_eligible(
    row: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    now: str,
) -> bool:
    if str(row.get("liveness") or "") == "stale":
        return True
    eligible = diagnostics.get("stale_eligible_at")
    if not eligible:
        return False
    try:
        return parse_stamp(str(eligible)) <= parse_stamp(now)
    except ValueError:
        return False


def current_holdings_health_by_session(
    conn: Any,
    rows: list[dict[str, Any]],
    identities: Mapping[str, Mapping[str, Any]],
    diagnostics: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Project one Currently held tone per roster session."""
    stamp = _stamp(now)
    session_ids = _session_ids(rows)
    claimed = _claimed_item_rows(conn, session_ids)
    qa_failed = _qa_failed_item_ids(
        conn,
        [int(row["item_id"]) for row in claimed if row.get("item_id") is not None],
    )
    by_session: dict[str, list[dict[str, Any]]] = {}
    for claim in claimed:
        by_session.setdefault(str(claim["session_id"]), []).append(claim)
    projected: dict[str, str] = {}
    for row in rows:
        session_id = str(row.get("session_id") or "")
        identity = identities.get(session_id, {})
        items = by_session.get(session_id, [])
        claimed_at = next(
            (
                str(item.get("claimed_at") or "")
                for item in items
                if item.get("claimed_at")
            ),
            "",
        )
        last_activity = str(identity.get("last_tool_call_at") or claimed_at or "")
        staffing, idle_after = _policy_seconds(conn, row.get("project_id"))
        projected[session_id] = classify_current_holdings_health(
            parked=session_is_parked(row.get("mode")),
            idle_seconds=age_seconds(last_activity, stamp) or 0,
            staffing_after_seconds=staffing,
            idle_after_seconds=idle_after,
            stale_eligible=_stale_eligible(
                row, diagnostics.get(session_id, {}), stamp
            ),
            item_blocked=any(int(item.get("blocked") or 0) for item in items),
            landed_open=any(_landed_open(item) for item in items),
            qa_failed=any(
                int(item["item_id"]) in qa_failed
                for item in items
                if item.get("item_id") is not None
            ),
        )
    return projected


__all__ = [
    "HOLDINGS_HEALTH_GREEN",
    "HOLDINGS_HEALTH_ORANGE",
    "HOLDINGS_HEALTH_RED",
    "HOLDINGS_HEALTH_TONES",
    "HOLDINGS_HEALTH_YELLOW",
    "classify_current_holdings_health",
    "current_holdings_health_by_session",
]

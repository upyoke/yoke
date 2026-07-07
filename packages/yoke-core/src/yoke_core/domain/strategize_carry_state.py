"""State transitions and candidate-set construction for Strategize carry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.strategize_carry_schema import (
    DEFAULT_CARRY_LIMIT,
    DEFAULT_HORIZON_DAYS,
    VALID_STATES,
    ensure_schema,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _iso_utc_now() -> str:
    """Return an ISO 8601 UTC timestamp (``Z`` suffix)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` suffix tolerated)."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _horizon_cutoff(now_iso: str, horizon_days: int) -> str:
    """Return the horizon cutoff ISO timestamp for ``register_new_landings``."""
    now = _parse_iso(now_iso)
    cutoff = now - timedelta(days=max(horizon_days, 0))
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_days(first_seen_at: str, now_iso: str) -> int:
    """Return integer days between ``first_seen_at`` and ``now_iso`` (>=0)."""
    try:
        seen = _parse_iso(first_seen_at)
        now = _parse_iso(now_iso)
    except ValueError:
        return 0
    delta = now - seen
    return max(delta.days, 0)


def register_new_landings(
    conn: Any,
    project: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    now_iso: Optional[str] = None,
) -> List[int]:
    """Register any landed items within ``horizon_days`` that are not yet tracked.

    Scans ``items`` for rows with the given ``project`` whose ``merged_at`` is
    newer than ``now - horizon_days``, inserts ``pending`` carry rows for any
    that are not already present, and returns the list of newly inserted
    ``item_id`` values (integers).

    The scan intentionally ignores rows that are already in the carry table,
    so previously-reflected and previously-dismissed items are not re-added as
    pending on every refresh.
    """
    ensure_schema(conn)
    project_id = resolve_project_id(conn, project)
    now_iso = now_iso or _iso_utc_now()
    cutoff = _horizon_cutoff(now_iso, horizon_days)
    project_id = resolve_project_id(conn, project)
    p = _p(conn)

    try:
        candidate_rows = conn.execute(
            "SELECT id FROM items "
            f" WHERE project_id = {p} "
            "   AND merged_at IS NOT NULL "
            f"   AND merged_at >= {p}",
            (project_id, cutoff),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        conn.rollback()
        return []

    new_ids: List[int] = []
    for row in candidate_rows:
        item_id = row["id"] if hasattr(row, "keys") else row[0]
        if item_id is None:
            continue
        cur = conn.execute(
            "INSERT INTO strategize_landed_carry "
            "(item_id, project_id, state, first_seen_at, last_updated_at) "
            f"VALUES ({p}, {p}, 'pending', {p}, {p}) "
            "ON CONFLICT(project_id, item_id) DO NOTHING",
            (int(item_id), project_id, now_iso, now_iso),
        )
        if cur.rowcount > 0:
            new_ids.append(int(item_id))
    conn.commit()
    return new_ids


def get_candidate_set(
    conn: Any,
    project: str,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    carry_limit: int = DEFAULT_CARRY_LIMIT,
    now_iso: Optional[str] = None,
    new_ids: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """Return the classified bounded carry-forward candidate set."""
    ensure_schema(conn)
    project_id = resolve_project_id(conn, project)
    now_iso = now_iso or _iso_utc_now()
    horizon_cutoff = _horizon_cutoff(now_iso, horizon_days)
    new_set: Set[int] = set(int(i) for i in (new_ids or []))
    project_id = resolve_project_id(conn, project)
    p = _p(conn)

    rows = conn.execute(
        f"""
        SELECT c.item_id, c.state, c.first_seen_at, c.last_updated_at,
               c.last_session_id, c.reason,
               i.title, i.priority, i.merged_at
          FROM strategize_landed_carry c
          LEFT JOIN items i ON i.id = c.item_id
         WHERE c.project_id = {p}
         ORDER BY
           CASE c.state
             WHEN 'pending' THEN 0
             WHEN 'reflected' THEN 1
             ELSE 2
           END,
           COALESCE(i.merged_at, c.first_seen_at) DESC,
           c.item_id DESC
         LIMIT {p}
        """,
        (project_id, carry_limit + 1),
    ).fetchall()

    truncated = len(rows) > carry_limit
    rows = rows[:carry_limit]

    bucket_new: List[Dict[str, Any]] = []
    bucket_carry: List[Dict[str, Any]] = []
    bucket_reflected: List[Dict[str, Any]] = []
    bucket_dismissed: List[Dict[str, Any]] = []

    for row in rows:
        item_id = int(row[0])
        entry: Dict[str, Any] = {
            "item_id": item_id,
            "yok_id": f"YOK-{item_id}",
            "state": row[1],
            "first_seen_at": row[2] or "",
            "last_updated_at": row[3] or "",
            "last_session_id": row[4] or "",
            "reason": row[5] or "",
            "title": row[6] or "",
            "priority": (row[7] or "low"),
            "delivered_at": row[8] or "",
            "age_days": _age_days(row[2] or now_iso, now_iso),
        }
        state = entry["state"]
        if state == "pending":
            if item_id in new_set:
                bucket_new.append(entry)
            else:
                bucket_carry.append(entry)
        elif state == "reflected":
            bucket_reflected.append(entry)
        else:
            bucket_dismissed.append(entry)

    return {
        "project": project,
        "horizon_days": horizon_days,
        "horizon_cutoff": horizon_cutoff,
        "carry_limit": carry_limit,
        "now": now_iso,
        "new": bucket_new,
        "carry_forward": bucket_carry,
        "reflected": bucket_reflected,
        "dismissed": bucket_dismissed,
        "total_pending": len(bucket_new) + len(bucket_carry),
        "truncated": truncated,
    }


def mark_items(
    conn: Any,
    project: str,
    item_ids: Sequence[int],
    state: str,
    session_id: Optional[str] = None,
    reason: Optional[str] = None,
    now_iso: Optional[str] = None,
) -> int:
    """Update the carry state for a set of items."""
    if state not in VALID_STATES:
        raise ValueError(
            f"invalid strategize carry state {state!r}; "
            f"expected one of {sorted(VALID_STATES)}"
        )
    ensure_schema(conn)
    project_id = resolve_project_id(conn, project)
    now_iso = now_iso or _iso_utc_now()
    project_id = resolve_project_id(conn, project)
    changed = 0
    p = _p(conn)
    for raw_id in item_ids:
        try:
            item_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        cur = conn.execute(
            "UPDATE strategize_landed_carry "
            f"   SET state = {p}, last_updated_at = {p}, "
            f"       last_session_id = {p}, reason = {p} "
            f" WHERE project_id = {p} AND item_id = {p}",
            (state, now_iso, session_id, reason, project_id, item_id),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO strategize_landed_carry "
                "(item_id, project_id, state, first_seen_at, "
                " last_updated_at, last_session_id, reason) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
                (item_id, project_id, state, now_iso, now_iso, session_id, reason),
            )
            changed += 1
        else:
            changed += cur.rowcount
    conn.commit()
    return changed

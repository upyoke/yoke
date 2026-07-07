"""Chain-head freshness evaluator for ``/yoke conduct`` re-entry.

Given a parent epic id, a task number, and the current session id,
return whether a chain head at ``implementing`` /
``reviewing-implementation`` is ``"resumable"``, ``"busy"``, or
``"blocked"``. Two conduct surfaces consume this decision and must not drift:
``entry-activation-resolution.md`` S6c and ``dispatch-context.md`` 5f-epic.2.

* ``resumable`` — re-dispatch via ``5f-rehydrate``.
* ``busy`` — recent session/task activity; defer to SessionEnd defense.
* ``blocked`` — another live session holds the parent claim.

Implementation invariants: DB-only (no subprocess to ``who-claims``),
freshness threshold via :func:`resolve_freshness_window_s` (default 60s,
machine config key ``chain_head_freshness_window_s``), recent task
activity read from ``epic_tasks.last_activity_at`` (first-class state,
The telemetry-only events cutover keeps per-task scoping structural), and every branch returns a
structured rationale rather than silently falling through on missing or
malformed evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .runtime_settings import get_seconds
from .session_reclaim_activity import latest_activity
from .yoke_function_dispatch_claims import who_claims_for_item
from . import db_backend


STATUS_RESUMABLE = "resumable"
STATUS_BUSY = "busy"
STATUS_BLOCKED = "blocked"


DEFAULT_FRESHNESS_WINDOW_S = 60


@dataclass(frozen=True)
class FreshnessEvidence:
    """Structured evidence the evaluator gathered before deciding."""

    holder_session_id: Optional[str]
    holder_is_self: bool
    prior_session_id: Optional[str]
    prior_session_ended: bool
    prior_heartbeat_age_s: Optional[int]
    recent_task_activity_age_s: Optional[int]
    freshness_window_s: int

    def as_dict(self) -> dict:
        return {
            "holder_session_id": self.holder_session_id,
            "holder_is_self": self.holder_is_self,
            "prior_session_id": self.prior_session_id,
            "prior_session_ended": self.prior_session_ended,
            "prior_heartbeat_age_s": self.prior_heartbeat_age_s,
            "recent_task_activity_age_s": self.recent_task_activity_age_s,
            "freshness_window_s": self.freshness_window_s,
        }


@dataclass(frozen=True)
class FreshnessDecision:
    """Outcome of the per-chain-head freshness check."""

    status: str  # one of STATUS_RESUMABLE / STATUS_BUSY / STATUS_BLOCKED
    rationale: str
    evidence: FreshnessEvidence


def resolve_freshness_window_s(*, override_s: Optional[int] = None) -> int:
    """Resolve the chain-head freshness window from config or override.

    The default is 60 seconds. Operators tune the threshold by setting
    ``chain_head_freshness_window_s`` in machine config; tests pass
    ``override_s`` directly.
    """
    if override_s is not None and override_s > 0:
        return int(override_s)
    return get_seconds(
        "chain_head_freshness_window_s",
        DEFAULT_FRESHNESS_WINDOW_S,
    )


def _parse_iso(ts: object) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp tolerantly; return None on malformed input."""
    if ts is None:
        return None
    text = str(ts).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(ts: object, now: datetime) -> Optional[int]:
    parsed = _parse_iso(ts)
    if parsed is None:
        return None
    delta = now - parsed
    return int(delta.total_seconds())


def _connect_default() -> Any:
    """Open the canonical control-plane DB via db_helpers."""
    from . import db_helpers
    return db_helpers.connect()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row, key: str):
    """Read a column from row-like objects by name."""
    if row is None:
        return None
    if hasattr(row, "keys"):
        try:
            return row[key]
        except (IndexError, KeyError):
            return None
    return None


def _prior_session_for_epic(
    conn: Any, epic_id: int, current_session_id: str
) -> Optional[str]:
    """Return the most recent ``work_claims.session_id`` for ``epic_id``,
    excluding the current session's own claim rows.

    "Prior" means "before the current invocation." The current session's
    own active claim (from S3b ``claim-work``) and any earlier
    released-then-re-claimed rows belonging to the same session must not
    be returned: their heartbeats reflect the live session itself
    (refreshed by ``session-touch``), not any competing dispatch. When the
    only prior rows belong to the current session, return ``None`` and
    let the caller fall through to "no prior session row" semantics.
    """
    row = conn.execute(
        "SELECT session_id FROM work_claims "
        f"WHERE target_kind='item' AND item_id={_p(conn)} "
        f"AND session_id <> {_p(conn)} "
        "ORDER BY claimed_at DESC, id DESC LIMIT 1",
        (int(epic_id), str(current_session_id)),
    ).fetchone()
    if row is None:
        return None
    sid = _row_value(row, "session_id")
    if not sid:
        return None
    return str(sid)


def _session_activity_row(
    conn: Any, session_id: str
) -> Optional[tuple[object, object]]:
    """Return ``(activity_at, ended_at)`` for ``session_id`` or ``None``."""
    row = conn.execute(
        f"SELECT ended_at FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return latest_activity(conn, session_id), _row_value(row, "ended_at")


def _task_last_activity_at(
    conn: Any, epic_id: int, task_num: int
) -> Optional[object]:
    """Return ``epic_tasks.last_activity_at`` for ``(epic_id, task_num)``.

    First-class task-freshness state, stamped by every epic-task mutation
    surface. NULL means no mutation recorded — treated as absent. Returns
    ``None`` on fixture schemas without the column or table.
    """
    try:
        row = conn.execute(
            "SELECT last_activity_at FROM epic_tasks "
            f"WHERE epic_id = {_p(conn)} AND task_num = {_p(conn)}",
            (str(int(epic_id)), int(task_num)),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    if row is None:
        return None
    return _row_value(row, "last_activity_at")


def evaluate_chain_head_freshness(
    epic_id: int,
    task_num: int,
    current_session_id: str,
    *,
    conn: Optional[Any] = None,
    freshness_window_s: Optional[int] = None,
    now: Optional[datetime] = None,
) -> FreshnessDecision:
    """Decide whether a chain head at ``implementing`` / ``reviewing-implementation``
    should be treated as ``resumable``, ``busy``, or ``blocked``.

    The caller filters by lifecycle status before invoking this helper —
    the evaluator itself does not re-check ``epic_tasks.status``; its
    only concern is whether the in-flight status is stale.
    """
    window = resolve_freshness_window_s(override_s=freshness_window_s)
    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    holder = who_claims_for_item(int(epic_id))
    holder_session_id: Optional[str] = None
    holder_is_self = False
    if holder:
        holder_sid_raw = holder.get("session_id")
        if holder_sid_raw:
            holder_session_id = str(holder_sid_raw)
            holder_is_self = holder_session_id == str(current_session_id)

    if holder_session_id is not None and not holder_is_self:
        evidence = FreshnessEvidence(
            holder_session_id=holder_session_id,
            holder_is_self=False,
            prior_session_id=None,
            prior_session_ended=False,
            prior_heartbeat_age_s=None,
            recent_task_activity_age_s=None,
            freshness_window_s=window,
        )
        return FreshnessDecision(
            status=STATUS_BLOCKED,
            rationale=(
                f"parent epic claim is held by another live session "
                f"{holder_session_id!r}"
            ),
            evidence=evidence,
        )

    owns_conn = False
    if conn is None:
        conn = _connect_default()
        owns_conn = True
    try:
        prior_sid = _prior_session_for_epic(
            conn, epic_id, str(current_session_id)
        )
        prior_ended = False
        prior_age_s: Optional[int] = None
        if prior_sid:
            hb_row = _session_activity_row(conn, prior_sid)
            if hb_row is not None:
                last_hb, ended_at = hb_row
                prior_ended = bool(ended_at)
                prior_age_s = _age_seconds(last_hb, now_dt)

        recent_ts = _task_last_activity_at(conn, epic_id, task_num)
        recent_age_s = _age_seconds(recent_ts, now_dt)
    finally:
        if owns_conn:
            conn.close()

    heartbeat_within_window = (
        prior_age_s is not None and prior_age_s < window
    )
    task_activity_within_window = (
        recent_age_s is not None and recent_age_s < window
    )

    evidence = FreshnessEvidence(
        holder_session_id=holder_session_id,
        holder_is_self=holder_is_self,
        prior_session_id=prior_sid,
        prior_session_ended=prior_ended,
        prior_heartbeat_age_s=prior_age_s,
        recent_task_activity_age_s=recent_age_s,
        freshness_window_s=window,
    )

    if heartbeat_within_window and task_activity_within_window:
        rationale = (
            f"prior session {prior_sid!r} activity age "
            f"{prior_age_s}s and most recent task activity age "
            f"{recent_age_s}s are both inside freshness window "
            f"{window}s"
        )
        return FreshnessDecision(STATUS_BUSY, rationale, evidence)
    if heartbeat_within_window:
        rationale = (
            f"prior session {prior_sid!r} activity age "
            f"{prior_age_s}s is inside freshness window {window}s"
        )
        return FreshnessDecision(STATUS_BUSY, rationale, evidence)
    if task_activity_within_window:
        rationale = (
            f"most recent task activity for ({epic_id},{task_num}) age "
            f"{recent_age_s}s is inside freshness window {window}s"
        )
        return FreshnessDecision(STATUS_BUSY, rationale, evidence)

    rationale_parts: list[str] = [
        "parent claim held by current session"
        if holder_is_self else "no live holder of parent claim"
    ]
    if prior_sid is None:
        rationale_parts.append("no prior session row")
    elif prior_age_s is None:
        rationale_parts.append(
            f"prior session {prior_sid!r} activity unparseable or missing"
        )
    else:
        rationale_parts.append(
            f"prior session {prior_sid!r} activity age {prior_age_s}s "
            f"outside freshness window {window}s"
        )
    if recent_age_s is None:
        rationale_parts.append(
            f"no recorded task activity for ({epic_id},{task_num})"
        )
    else:
        rationale_parts.append(
            f"most recent task activity age {recent_age_s}s outside "
            f"freshness window {window}s"
        )
    rationale = "; ".join(rationale_parts)
    return FreshnessDecision(STATUS_RESUMABLE, rationale, evidence)


__all__ = [
    "DEFAULT_FRESHNESS_WINDOW_S",
    "FreshnessDecision",
    "FreshnessEvidence",
    "STATUS_BLOCKED",
    "STATUS_BUSY",
    "STATUS_RESUMABLE",
    "evaluate_chain_head_freshness",
    "resolve_freshness_window_s",
]

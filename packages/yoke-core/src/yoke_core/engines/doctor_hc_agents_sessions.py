"""Session lifecycle health checks — stale session files, reclaimer
liveness, and stale-reclaim collision observability.

HC functions ensuring stale session files are reaped, the
HarnessSessionStaleSweepCompleted heartbeat fires within cadence, and
that no ``WorkReclaimed`` event is followed by post-reclaim activity
from the original session within the staleness window (the silent
two-session collision shape this HC observes pre-fix collisions for and
guards against regressions of the TOCTOU recheck path).

HC functions:

- HC-stale-sessions
- HC-stale-session-reclaimer-alive
- HC-stale-reclaim-collision (24-hour look-back; quiet when zero
  collisions are present)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

import yoke_core.engines.doctor_report as _base

from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_stale_sessions(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stale-sessions: Stale session files."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-stale-sessions", "Stale session files", "PASS", "")
        return

    data_root = Path(repo_root) / "data"
    config_path = data_root / "config"

    # Check if session registry is enabled
    enabled = False
    if config_path.is_file():
        for line in config_path.read_text(errors="replace").splitlines():
            if line.strip().startswith("session_registry_enabled="):
                enabled = line.strip().split("=", 1)[1].strip() == "true"

    if not enabled:
        rec.record("HC-stale-sessions", "Stale session files (session registry disabled)", "PASS", "")
        return

    sessions_dir = data_root / "sessions"
    if not sessions_dir.is_dir():
        rec.record("HC-stale-sessions", "Stale session files", "PASS", "")
        return

    now = time.time()
    four_hours = 14400
    issues: List[str] = []
    for sfile in sorted(sessions_dir.glob("*.session")):
        age = now - sfile.stat().st_mtime
        if age > four_hours:
            hours = int(age // 3600)
            issues.append(f"- {sfile.name}: stale ({hours}h old)")

    if issues:
        rec.record("HC-stale-sessions", "Stale session files", "WARN", "\n".join(issues))
    else:
        rec.record("HC-stale-sessions", "Stale session files", "PASS", "")


def hc_stale_session_reclaimer_alive(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stale-session-reclaimer-alive: Verify the stale-session sweep is running.

    Checks that a HarnessSessionStaleSweepCompleted event has been emitted within the
    documented cadence.  The sweep fires on every session-start hook invocation
    and from the periodic clean-stale-sessions CLI.  A gap longer than 2 hours
    suggests the reclaimer is not running.
    """
    slug = "HC-stale-session-reclaimer-alive"
    label = "Stale-session reclaimer alive"

    if not _table_exists(conn, "events"):
        rec.record(slug, label, "PASS", "No events table — skipping")
        return

    row = conn.execute(
        "SELECT MAX(created_at) AS latest FROM events "
        "WHERE event_name = 'HarnessSessionStaleSweepCompleted'",
    ).fetchone()

    if not row or not row["latest"]:
        # No sweep events at all — may be a fresh deployment
        rec.record(
            slug, label, "WARN",
            "No HarnessSessionStaleSweepCompleted events found. "
            "The stale-session reclaimer may not be running. "
            "It fires via session-start hooks and clean-stale-sessions CLI.",
        )
        return

    from datetime import datetime as _dt, timezone as _tz
    try:
        latest_str = row["latest"]
        latest_dt = _dt.fromisoformat(latest_str.replace("Z", "+00:00"))
        if latest_dt.tzinfo is None:
            # Older rows may carry naive UTC timestamps.
            latest_dt = latest_dt.replace(tzinfo=_tz.utc)
        age_minutes = int((_dt.now(_tz.utc) - latest_dt).total_seconds() / 60)
    except (ValueError, TypeError):
        rec.record(slug, label, "WARN", f"Cannot parse latest sweep timestamp: {row['latest']}")
        return

    max_gap_minutes = 120  # 2 hours
    if age_minutes > max_gap_minutes:
        rec.record(
            slug, label, "WARN",
            f"Last HarnessSessionStaleSweepCompleted was {age_minutes}m ago "
            f"(threshold: {max_gap_minutes}m). Reclaimer may be stalled.",
        )
    else:
        rec.record(slug, label, "PASS", f"Last sweep {age_minutes}m ago")


def hc_stale_reclaim_collision(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stale-reclaim-collision: Surface silent two-session collisions.

    Observability surface for the race shape — surfaces any
    ``WorkReclaimed`` event whose original session emitted further
    tool-call activity within the staleness window after the reclaim
    timestamp. The check is quiet when zero collisions are present and
    only emits when at least one collision exists in the look-back
    window. This includes pre-fix collisions still in the events table
    plus regressions of the TOCTOU recheck path.

    Look-back window: 24 hours.

    Resolves the per-row staleness window from
    ``DEFAULT_STALE_THRESHOLD_MINUTES`` and the codex executor override
    via the shared TTL resolver — no caller-side threshold literal.
    """
    slug = "HC-stale-reclaim-collision"
    label = "Silent two-session reclaim collisions"

    if not _table_exists(conn, "events"):
        rec.record(slug, label, "PASS", "No events table — skipping")
        return

    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    from yoke_core.domain.session_reclaim_activity import resolve_effective_ttl
    from yoke_core.domain.sql_json import json_get

    look_back_hours = 24
    look_back_cutoff = (
        _dt.now(_tz.utc) - _td(hours=look_back_hours)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    reclaim_rows = conn.execute(
        f"""SELECT e.created_at AS reclaimed_at,
                  e.session_id AS session_id,
                  {json_get('e.envelope', '$.context.detail.claim_id')} AS claim_id
           FROM events e
           WHERE e.event_name = 'WorkReclaimed'
             AND e.created_at >= %s
           ORDER BY e.created_at DESC""",
        (look_back_cutoff,),
    ).fetchall()

    issues: list[str] = []
    for row in reclaim_rows:
        sid = row["session_id"] if hasattr(row, "keys") else row[1]
        reclaimed_at = row["reclaimed_at"] if hasattr(row, "keys") else row[0]
        claim_id = row["claim_id"] if hasattr(row, "keys") else row[2]
        if not sid or not reclaimed_at:
            continue

        executor_row = conn.execute(
            "SELECT executor FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        executor = (
            (executor_row["executor"] if executor_row and hasattr(executor_row, "keys")
             else (executor_row[0] if executor_row else None))
            or "unknown"
        )

        ttl_minutes = resolve_effective_ttl(executor)

        try:
            reclaim_dt = _dt.fromisoformat(
                reclaimed_at.replace("Z", "+00:00") if reclaimed_at.endswith("Z")
                else reclaimed_at
            )
        except (AttributeError, ValueError):
            continue
        if reclaim_dt.tzinfo is None:
            reclaim_dt = reclaim_dt.replace(tzinfo=_tz.utc)
        window_end = reclaim_dt + _td(minutes=ttl_minutes)

        post_activity_row = conn.execute(
            """SELECT COUNT(*) AS cnt
               FROM events
               WHERE event_name IN ('HarnessToolCallCompleted', 'HarnessToolCallFailed')
                 AND session_id = %s
                 AND created_at > %s
                 AND created_at <= %s""",
            (sid, reclaimed_at, window_end.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ).fetchone()
        post_count = int(
            (post_activity_row["cnt"] if hasattr(post_activity_row, "keys")
             else post_activity_row[0]) or 0
        )
        if post_count > 0:
            claim_label = f"claim={claim_id}" if claim_id else "claim=unknown"
            issues.append(
                f"- session {sid} ({claim_label}) reclaimed at {reclaimed_at}; "
                f"{post_count} tool-call event(s) emitted within {ttl_minutes}m "
                f"after reclaim (executor={executor})"
            )

    if issues:
        rec.record(
            slug, label, "WARN",
            f"Detected {len(issues)} reclaim collision(s) in last {look_back_hours}h:\n"
            + "\n".join(issues),
        )
        return

    rec.record(slug, label, "PASS", "")

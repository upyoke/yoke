"""Advisory detection for local main commits made during a session.

The checkout lives on the session's client machine, which reports the
newest commits of its ``main`` branch as the
:data:`~yoke_contracts.hook_runner.client_facts.MAIN_HEAD_KEY` fact. The
session row remembers the last head this session saw.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from yoke_contracts.timestamps import utc_now, parse_instant
from typing import Any, Mapping, Optional

from yoke_contracts.hook_runner.client_facts import main_head

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, instant_parameter

THROTTLE_SECONDS = 60


@dataclass(frozen=True)
class DriftAdvisory:
    session_id: str
    commits_ahead: int
    oneline_summary: str


def _parse_iso(raw: datetime | str | None) -> datetime | None:
    return parse_instant(raw) if raw is not None else None


def _commits_since(
    commits: list[tuple[str, str]], previous_sha: str
) -> tuple[int, str]:
    """Count and summarise the reported commits newer than *previous_sha*.

    The client reports a bounded window of ``main`` history; a previous
    head older than that window counts the whole window.
    """
    newer = []
    for sha, subject in commits:
        if sha == previous_sha:
            break
        newer.append((sha, subject))
    summary = "; ".join(f"{sha[:10]} {subject}".strip() for sha, subject in newer[:5])
    return len(newer), summary


def check_drift(
    session_id: str,
    payload: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
    throttle_seconds: int = THROTTLE_SECONDS,
) -> Optional[DriftAdvisory]:
    """Return a drift advisory when ``main`` moved since this session last checked."""
    commits = main_head(payload)
    if not session_id or commits is None:
        return None
    checked_dt = utc_now() if now is None else parse_instant(now)
    conn = connect()
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        try:
            row = conn.execute(
                "SELECT session_id, workspace, last_seen_main_sha, last_drift_check_at "
                f"FROM harness_sessions WHERE session_id={p}",
                (session_id,),
            ).fetchone()
        except db_backend.operational_error_types(conn):
            return None
        if row is None:
            return None
        prior_check = _parse_iso(row["last_drift_check_at"])
        if prior_check and checked_dt - prior_check < timedelta(
            seconds=throttle_seconds
        ):
            return None
        current_sha = commits[0][0]
        previous_sha = row["last_seen_main_sha"]
        conn.execute(
            f"UPDATE harness_sessions SET last_seen_main_sha={p}, "
            f"last_drift_check_at={p} WHERE session_id={p}",
            (current_sha, instant_parameter(conn, checked_dt), session_id),
        )
        conn.commit()
        if not previous_sha or previous_sha == current_sha:
            return None
        commits_ahead, summary = _commits_since(commits, previous_sha)
        return DriftAdvisory(session_id, commits_ahead, summary)
    finally:
        conn.close()


def format_advisory(advisory: DriftAdvisory) -> str:
    summary = advisory.oneline_summary or "summary unavailable"
    return (
        f"# advisory: another session committed {advisory.commits_ahead} "
        f"new commits to main: {summary}"
    )


__all__ = ["DriftAdvisory", "check_drift", "format_advisory"]

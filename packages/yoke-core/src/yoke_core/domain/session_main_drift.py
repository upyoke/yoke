"""Advisory detection for local main commits made during a session."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now

THROTTLE_SECONDS = 60


@dataclass(frozen=True)
class DriftAdvisory:
    session_id: str
    commits_ahead: int
    oneline_summary: str


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _git(repo_path: str, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", repo_path, *args],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _repo_path(row: Any, explicit: Optional[str]) -> Optional[str]:
    candidate = explicit or row["workspace"]
    if not candidate:
        return None
    path = Path(candidate)
    return str(path if path.is_dir() else path.parent)


def _commit_summary(repo_path: str, old_sha: str) -> tuple[int, str]:
    try:
        count = int(_git(repo_path, "rev-list", "--count", f"{old_sha}..main") or "0")
        summary = _git(repo_path, "log", "--oneline", "-5", f"{old_sha}..main")
    except Exception:
        return 0, ""
    return count, "; ".join(line.strip() for line in summary.splitlines() if line.strip())


def check_drift(
    session_id: str,
    *,
    db_path: Optional[str] = None,
    repo_path: Optional[str] = None,
    now: Optional[str] = None,
    throttle_seconds: int = THROTTLE_SECONDS,
) -> Optional[DriftAdvisory]:
    """Return a drift advisory when ``main`` moved since this session last checked."""
    if not session_id:
        return None
    checked_at = now or iso8601_now()
    checked_dt = _parse_iso(checked_at) or datetime.now(timezone.utc)
    conn = connect(path=db_path)
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
        if prior_check and (checked_dt - prior_check).total_seconds() < throttle_seconds:
            return None
        resolved_repo = _repo_path(row, repo_path)
        if not resolved_repo:
            return None
        try:
            current_sha = _git(resolved_repo, "rev-parse", "main")
        except Exception:
            return None
        previous_sha = row["last_seen_main_sha"]
        conn.execute(
            f"UPDATE harness_sessions SET last_seen_main_sha={p}, "
            f"last_drift_check_at={p} WHERE session_id={p}",
            (current_sha, checked_at, session_id),
        )
        conn.commit()
        if not previous_sha or previous_sha == current_sha:
            return None
        commits_ahead, summary = _commit_summary(resolved_repo, previous_sha)
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

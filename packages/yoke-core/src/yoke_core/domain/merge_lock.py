"""DB-based merge lock — Python owner.

Sole owner of merge-lock semantics. Callers invoke the CLI below or import
the module directly; there is no shell wrapper.

Provides:
  - ``check`` — query for active (non-expired) lock rows with smart stale detection
  - ``acquire`` — insert a new lock row with PID-based session ID and configurable TTL
  - ``release`` — delete the row for the current session
  - ``force_clear`` — delete ALL lock rows (emergency)

CLI usage::

    python3 -m yoke_core.domain.merge_lock check
    python3 -m yoke_core.domain.merge_lock acquire <branch> [epic_id]
    python3 -m yoke_core.domain.merge_lock release <session_id> <branch>
    python3 -m yoke_core.domain.merge_lock force-clear
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

from yoke_core.domain import db_backend, runtime_settings
from yoke_core.domain import merge_lock_contention as contention
from yoke_core.domain.merge_lock_contention import LockScope
from yoke_core.domain import control_plane_transport as _transport


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

DEFAULT_TTL_MINUTES = 30


def _repo_root() -> Path:
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _db_path() -> str:
    """Return the retired DB path token for legacy call signatures."""
    return ""


def _connect():
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _local_connection_or_none() -> Optional[Any]:
    return _transport.local_connection_or_none(_connect)


def _relay(function_id: str, payload: dict) -> dict:
    return _transport.relay(function_id, payload)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MergeLock:
    """A single row from the merge_locks table."""
    id: int
    session_id: str
    branch: str
    epic_id: Optional[str]
    acquired_at: str
    expires_at: str
    project_slug: Optional[str] = None
    target_branch: Optional[str] = None


@dataclass
class LockHandle:
    """Returned by acquire(); pass to release() to release."""
    session_id: str
    branch: str
    scope: LockScope = field(default_factory=LockScope)


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def _rows_over_transport(now: str) -> list[dict]:
    return list(_relay("merge.lock.list", {"now": now}).get("rows") or [])


def _rows_over_connection(conn: Any, now: str) -> list[dict]:
    """Drop expired rows, then read whatever still holds the lock."""
    p = _p(conn)
    conn.execute(f"DELETE FROM merge_locks WHERE expires_at < {p}", (now,))
    conn.commit()
    rows = conn.execute(
        "SELECT id, session_id, branch, COALESCE(epic_id, ''), "
        "project_slug, target_branch FROM merge_locks"
    ).fetchall()
    return [
        {
            "id": row[0],
            "session_id": row[1],
            "branch": row[2],
            "epic_id": row[3],
            "project_slug": row[4],
            "target_branch": row[5],
        }
        for row in rows
    ]


def check(
    conn: Optional[Any] = None,
    *,
    scope: Optional[LockScope] = None,
) -> Optional[str]:
    """Report what contends with *scope*, retiring holders that have died.

    Returns None when nothing contends, else a message naming the holder.
    Rows outside the scope are neither reported nor retired — they belong to
    a live merge somewhere else and are not this caller's to judge.
    """
    scope = scope or LockScope()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    owned = _local_connection_or_none() if conn is None else None
    live = conn if conn is not None else owned
    try:
        rows = (
            _rows_over_connection(live, now) if live is not None
            else _rows_over_transport(now)
        )
        verdict = contention.evaluate(rows, scope)
        if verdict.stale_ids:
            _release_ids(verdict.stale_ids, live)
        return verdict.blocked_by
    finally:
        if owned is not None:
            owned.close()


def _release_ids(lock_ids: Sequence[int], conn: Optional[Any]) -> None:
    """Retire rows whose holder has died, over whichever path is live."""
    if conn is None:
        _relay("merge.lock.release", {"lock_ids": list(lock_ids)})
        return
    p = _p(conn)
    for lock_id in lock_ids:
        conn.execute(f"DELETE FROM merge_locks WHERE id = {p}", (lock_id,))
    conn.commit()


def acquire(
    branch: str,
    epic_id: Optional[str] = None,
    *,
    conn: Optional[Any] = None,
    ttl_minutes: Optional[int] = None,
    scope: Optional[LockScope] = None,
) -> LockHandle:
    """Acquire a merge lock.

    Returns a LockHandle for later release.
    Raises RuntimeError if the lock cannot be acquired (table issue).
    """
    if not branch:
        raise ValueError("acquire requires a branch argument")

    if ttl_minutes is None:
        ttl_minutes = runtime_settings.get_int(
            "merge_lock_ttl_minutes", DEFAULT_TTL_MINUTES,
        )

    now = datetime.now(timezone.utc)
    pid = os.environ.get("YOKE_MERGE_LOCK_PID") or str(os.getpid())
    session_id = f"{pid}-{int(now.timestamp())}"
    acquired_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = (now + timedelta(minutes=ttl_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    scope = scope or LockScope()
    owned = _local_connection_or_none() if conn is None else None
    live = conn if conn is not None else owned
    if live is None:
        _relay("merge.lock.acquire", {
            "session_id": session_id,
            "branch": branch,
            "epic_id": epic_id or None,
            "acquired_at": acquired_at,
            "expires_at": expires_at,
            "project_slug": scope.project_slug,
            "target_branch": scope.target_branch,
        })
        return LockHandle(session_id=session_id, branch=branch, scope=scope)

    conn = live
    try:
        p = _p(conn)
        conn.execute(
            "INSERT INTO merge_locks (session_id, branch, epic_id, acquired_at, "
            "expires_at, project_slug, target_branch) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (
                session_id, branch, epic_id if epic_id else None,
                acquired_at, expires_at,
                scope.project_slug, scope.target_branch,
            ),
        )
        conn.commit()

        return LockHandle(session_id=session_id, branch=branch, scope=scope)
    finally:
        if owned is not None:
            owned.close()


def release(
    handle: LockHandle,
    *,
    conn: Optional[Any] = None,
) -> None:
    """Release a merge lock by session_id and branch."""
    if not handle.session_id or not handle.branch:
        return

    owned = _local_connection_or_none() if conn is None else None
    live = conn if conn is not None else owned
    if live is None:
        _relay("merge.lock.release", {
            "session_id": handle.session_id, "branch": handle.branch,
        })
        return
    try:
        p = _p(live)
        live.execute(
            f"DELETE FROM merge_locks WHERE session_id = {p} AND branch = {p}",
            (handle.session_id, handle.branch),
        )
        live.commit()
    finally:
        if owned is not None:
            owned.close()


def force_clear(conn: Optional[Any] = None) -> None:
    """Delete ALL merge lock rows."""
    owned = _local_connection_or_none() if conn is None else None
    live = conn if conn is not None else owned
    if live is None:
        _relay("merge.lock.release", {"all_rows": True})
        return
    conn = live
    try:
        conn.execute("DELETE FROM merge_locks")
        conn.commit()
    finally:
        if owned is not None:
            owned.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: merge_lock.py <check|acquire|release|force-clear> [args...]", file=sys.stderr)
        return 2

    cmd = args[0]

    if cmd == "check":
        msg = check()
        if msg:
            print(msg, file=sys.stderr)
            return 1
        return 0

    elif cmd == "acquire":
        if len(args) < 2:
            print("Usage: merge_lock.py acquire <branch> [epic_id]", file=sys.stderr)
            return 2
        branch = args[1]
        epic_id = args[2] if len(args) > 2 else None
        handle = acquire(branch, epic_id)
        # Output session_id so the caller can pass it to release
        print(f"{handle.session_id}")
        return 0

    elif cmd == "release":
        if len(args) < 3:
            print("Usage: merge_lock.py release <session_id> <branch>", file=sys.stderr)
            return 2
        handle = LockHandle(session_id=args[1], branch=args[2])
        release(handle)
        return 0

    elif cmd == "force-clear":
        force_clear()
        return 0

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

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
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import db_backend, runtime_settings


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


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _pid_alive(pid: int) -> bool:
    """Check if a PID is still alive (POSIX)."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except (OSError, ValueError):
        return False


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


@dataclass
class LockHandle:
    """Returned by acquire(); pass to release() to release."""
    session_id: str
    branch: str


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def check(conn: Optional[Any] = None) -> Optional[str]:
    """Check for active blocking locks.

    Returns None if no blocking lock, or a message string if blocked.
    Side-effect: deletes expired and stale (dead-PID) rows.
    """
    own_conn = conn is None
    if own_conn:
        conn = _connect()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        p = _p(conn)

        # Step 1: delete expired rows
        conn.execute(f"DELETE FROM merge_locks WHERE expires_at < {p}", (now,))
        conn.commit()

        # Step 2: check remaining rows
        rows = conn.execute(
            "SELECT id, session_id, branch, COALESCE(epic_id, '') "
            "FROM merge_locks"
        ).fetchall()

        if not rows:
            return None

        block_msg = None
        for row in rows:
            row_id, session_id, branch, epic_id = row[0], row[1], row[2], row[3]
            # Extract PID from session_id (format: PID-epoch)
            parts = session_id.split("-", 1)
            try:
                pid = int(parts[0])
            except (ValueError, IndexError):
                pid = -1

            if pid > 0 and not _pid_alive(pid):
                # Stale lock — delete it
                conn.execute(f"DELETE FROM merge_locks WHERE id = {p}", (row_id,))
                conn.commit()
            else:
                epic_info = f" (epic: {epic_id})" if epic_id else ""
                block_msg = (
                    f"Merge lock held by session {session_id} "
                    f"on branch '{branch}'{epic_info}"
                )

        return block_msg
    finally:
        if own_conn:
            conn.close()


def acquire(
    branch: str,
    epic_id: Optional[str] = None,
    *,
    conn: Optional[Any] = None,
    ttl_minutes: Optional[int] = None,
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

    own_conn = conn is None
    if own_conn:
        conn = _connect()
    try:
        p = _p(conn)
        now = datetime.now(timezone.utc)
        pid = os.environ.get("YOKE_MERGE_LOCK_PID") or str(os.getpid())
        session_id = f"{pid}-{int(now.timestamp())}"
        acquired_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (now + timedelta(minutes=ttl_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn.execute(
            "INSERT INTO merge_locks (session_id, branch, epic_id, acquired_at, expires_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            (session_id, branch, epic_id if epic_id else None, acquired_at, expires_at),
        )
        conn.commit()

        return LockHandle(session_id=session_id, branch=branch)
    finally:
        if own_conn:
            conn.close()


def release(
    handle: LockHandle,
    *,
    conn: Optional[Any] = None,
) -> None:
    """Release a merge lock by session_id and branch."""
    if not handle.session_id or not handle.branch:
        return

    own_conn = conn is None
    if own_conn:
        conn = _connect()
    try:
        p = _p(conn)
        conn.execute(
            f"DELETE FROM merge_locks WHERE session_id = {p} AND branch = {p}",
            (handle.session_id, handle.branch),
        )
        conn.commit()
    finally:
        if own_conn:
            conn.close()


def force_clear(conn: Optional[Any] = None) -> None:
    """Delete ALL merge lock rows."""
    own_conn = conn is None
    if own_conn:
        conn = _connect()
    try:
        conn.execute("DELETE FROM merge_locks")
        conn.commit()
    finally:
        if own_conn:
            conn.close()


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

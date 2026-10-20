"""Shared worktree-invariant helpers for path-claim and session-cwd guards.

This module is a SHARED HELPER ONLY. It returns structured facts about the
active worktree-scoped item / session, the expected worktree root, the
current harness cwd, and whether it is inside a registered worktree.
Policy decisions (deny payload, suppression handling, orientation
rendering) live in the consumers:

* :mod:`yoke_core.domain.path_claim_bash_guard` — Bash-command file-mutation
  policy.
* :mod:`yoke_core.domain.lint_session_cwd` — session cwd binding policy
  and orientation.
* :mod:`yoke_core.domain.check_path_claim_coverage_at_commit` — pre-commit
  path-claim coverage gate.

Helpers are designed to be importable from those modules without a cyclic
import: they depend only on :mod:`yoke_core.domain.db_helpers` and the
standard library, and they take an injected database connection rather
than re-resolving the DB inside policy callers.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.domain.yok_n_parser import parse_item_argument


@dataclass(frozen=True)
class WorktreeInvariantContext:
    """Structured facts about the active worktree session.

    Consumers read these facts and decide their own policy. The helper
    never decides "deny" / "allow" — that's policy.
    """

    session_id: str
    item_id: Optional[int]
    worktree_branch: Optional[str]
    expected_worktree_root: Optional[str]
    actual_cwd: str
    is_inside_worktree: bool


def _resolve_session_id() -> str:
    """Return the ambient session id, or ``""`` when none resolves."""
    return resolve_ambient_session_id() or ""


def _normalize_item_id(
    raw: object, conn: Optional[Any] = None
) -> Optional[int]:
    """Resolve ``raw`` to the bare internal ``items.id``, or ``None``.

    Python integers pass through as internal ids. String digits resolve as
    project-local sequences, and public ``PREFIX-N`` refs resolve through the
    canonical parser on *conn* when supplied (the parser self-connects
    otherwise). Unparseable values yield ``None``.
    """
    if raw is not None and not isinstance(raw, (int, str)):
        raw = str(raw)
    try:
        return parse_item_argument(raw, conn=conn)
    except ValueError:
        return None


def _fetch_current_item_id(
    conn: Any, session_id: str
) -> Optional[int]:
    """Read ``harness_sessions.current_item_id`` for *session_id*.

    Returns the parsed integer or ``None`` when the session row is missing,
    its current item is NULL, or the value is unparseable. Errors are
    swallowed — the caller treats "no current item" as a silent no-op.
    """
    if not session_id:
        return None
    try:
        row = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        raw = row["current_item_id"] if hasattr(row, "keys") else row[0]
        # ``harness_sessions.current_item_id`` is a legacy textual
        # internal-id column. Its digit strings are storage values, not
        # operator-facing project sequences.
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        # Ref resolution may query project tables; keep it inside the
        # swallow block so a minimal fixture schema stays a silent no-op.
        return _normalize_item_id(raw, conn)
    except db_backend.database_error_types(conn):
        return None


def _detect_worktree_root(cwd: str) -> Optional[str]:
    """Return the main repo root for *cwd* when *cwd* is inside a worktree.

    Walks ``cwd`` looking for a ``.worktrees/<branch>/`` segment; the path
    above it is the main root. Returns None when *cwd* is not under a
    ``.worktrees/`` path.
    """
    parts = Path(cwd).resolve().parts
    for idx in range(len(parts) - 1, 0, -1):
        if parts[idx] == ".worktrees":
            return str(Path(*parts[:idx]))
    return None


def expected_worktree_path(main_root: str, lane_name: str) -> str:
    """Return the canonical worktree path for *lane_name* under *main_root*."""
    return str(Path(main_root) / ".worktrees" / lane_name)


def _lane_name_for_item(conn: Any, item_id: Optional[int]) -> Optional[str]:
    """The item's lane name (its public ref), or ``None`` when unresolved."""
    if item_id is None:
        return None
    from yoke_core.domain.worktree_naming import (
        ItemWorktreeIdentityUnresolved,
        worktree_name_for_item,
    )

    try:
        return worktree_name_for_item(conn, item_id)
    except ItemWorktreeIdentityUnresolved:
        return None


def _read_item_and_lane(
    conn: Optional[Any], session_id: str
) -> tuple[Optional[int], Optional[str]]:
    """Read the session's current item and its lane name in one connection."""
    if conn is not None:
        item_id = _fetch_current_item_id(conn, session_id)
        return item_id, _lane_name_for_item(conn, item_id)
    try:
        from yoke_core.domain import db_helpers
    except ImportError:
        return None, None
    try:
        opened = db_helpers.connect()
    except Exception:
        return None, None
    try:
        item_id = _fetch_current_item_id(opened, session_id)
        return item_id, _lane_name_for_item(opened, item_id)
    finally:
        try:
            opened.close()
        except Exception:
            pass


def resolve_active_worktree_context(
    conn: Optional[Any] = None,
    *,
    cwd: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[WorktreeInvariantContext]:
    """Resolve worktree-scoped facts for the active session.

    Returns ``None`` when no session id is available — consumers all
    treat that as a silent no-op rather than a deny. When a session id
    is available but the DB lookup yields no current item, the returned
    context carries ``item_id=None`` so consumers can still decide based
    on cwd shape alone.

    Parameters
    ----------
    conn:
        An existing database connection. When ``None``, the helper
        opens a read-only connection via :mod:`db_helpers`. Helper-opened
        connections are closed before return.
    cwd:
        Override the observed cwd. Defaults to ``os.getcwd()``.
    session_id:
        Override the session id. Defaults to the env-var resolution.
    """
    sid = session_id if session_id is not None else _resolve_session_id()
    if not sid:
        return None
    actual = cwd if cwd is not None else os.getcwd()
    main_root = _detect_worktree_root(actual)
    is_inside = main_root is not None
    item_id, branch = _read_item_and_lane(conn, sid)
    expected_root: Optional[str] = None
    if main_root and branch is not None:
        expected_root = expected_worktree_path(main_root, branch)
    return WorktreeInvariantContext(
        session_id=sid,
        item_id=item_id,
        worktree_branch=branch,
        expected_worktree_root=expected_root,
        actual_cwd=str(Path(actual).resolve()),
        is_inside_worktree=is_inside,
    )


__all__ = [
    "WorktreeInvariantContext",
    "expected_worktree_path",
    "resolve_active_worktree_context",
]


if __name__ == "__main__":  # pragma: no cover - diagnostic CLI
    import json

    ctx = resolve_active_worktree_context()
    if ctx is None:
        print(json.dumps({"context": None, "reason": "no session id"}))
        sys.exit(0)
    print(json.dumps({
        "session_id": ctx.session_id,
        "item_id": ctx.item_id,
        "worktree_branch": ctx.worktree_branch,
        "expected_worktree_root": ctx.expected_worktree_root,
        "actual_cwd": ctx.actual_cwd,
        "is_inside_worktree": ctx.is_inside_worktree,
    }, indent=2))

"""DB-side resolution of the active path claim for a hook session.

Both Edit/Write and Bash guards consume
:func:`resolve_active_claim_for_session` to find the claim attached to
the current session (or, fallback, the session's current item).

Resolution prefers typed ownership; the registering session is
provenance only and is never authority.

Resolution order:

1. ``owner_kind='session' AND owner_session_id = session_id`` with
   non-terminal state — most recent first. Catches the orphan/session
   claim case. Legacy un-typed rows match via ``session_id`` as well.
2. ``harness_sessions.current_item_id`` link, then
   ``owner_kind='item' AND owner_item_id = item`` for that item.
   The registering session is NOT a filter on this fallback — an
   item-owned claim survives any registering session ending.

The returned dict carries ``covered_paths``, ``worktree_path``
(absolute, issue items only) and ``chain_worktrees`` (epic items only,
tuple of ``(branch, absolute_path)`` pairs). ``item_type`` lets callers
pick the right field per evaluation.

:func:`_resolve_active_worktree` is the path-driven canonical reader
for "which worktree branch is this target bound to for this item?".
Issue items return ``items.worktree``; epic items return the chain
whose worktree path is an ancestor of the inbound ``target_path``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.project_checkout_locations import (
    checkout_for_project_id,
    item_worktree_path,
    worktree_path_for_branch,
)


_NON_TERMINAL_CLAIM_STATES = ("active", "planned", "blocked")


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_active_claim_for_session(
    *,
    session_id: str,
    conn: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Return the active claim attached to ``session_id`` as a dict.

    Returns ``None`` when nothing matches; never raises. Always closes
    a helper-opened connection.
    """
    if not session_id:
        return None
    own_conn = False
    if conn is None:
        try:
            from yoke_core.domain import db_helpers
        except ImportError:
            return None
        try:
            conn = db_helpers.connect()
            own_conn = True
        except Exception:
            return None
    try:
        return _resolve_active_claim(conn, session_id=session_id)
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _resolve_active_claim(
    conn: Any, *, session_id: str
) -> Optional[Dict[str, Any]]:
    """DB-side resolution; safe against missing tables (returns None).

    Prefers typed owner columns. A NULL ``owner_kind`` row (pre-
    migration) matches via the legacy ``session_id`` / ``item_id``
    columns; a typed row matches ONLY through its declared owner.
    """
    marker = _p(conn)
    placeholders = ",".join(marker for _ in _NON_TERMINAL_CLAIM_STATES)
    # Step 1: session-owned claims (typed owner_kind='session') OR
    # legacy un-typed rows where session_id matches.
    try:
        row = conn.execute(
            "SELECT id, item_id, integration_target, state "
            "FROM path_claims "
            f"WHERE state IN ({placeholders}) "
            "AND ("
            f"  (owner_kind = 'session' AND owner_session_id = {marker}) OR "
            f"  (owner_kind IS NULL AND session_id = {marker})"
            ") "
            "ORDER BY CASE state "
            "  WHEN 'active' THEN 0 "
            "  WHEN 'planned' THEN 1 "
            "  WHEN 'blocked' THEN 2 "
            "END, id DESC LIMIT 1",
            (*_NON_TERMINAL_CLAIM_STATES, session_id, session_id),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return None
    if row is None:
        item_id = _current_item_for_session(conn, session_id)
        if item_id is None:
            return None
        # Step 2: item-owned claims (typed owner_kind='item' on the
        # session's current item) OR legacy un-typed rows whose item_id
        # matches and whose session_id matches the calling session or
        # is NULL (cross-session leakage guard).
        try:
            row = conn.execute(
                "SELECT id, item_id, integration_target, state "
                "FROM path_claims "
                f"WHERE state IN ({placeholders}) "
                "AND ("
                f"  (owner_kind = 'item' AND owner_item_id = {marker}) OR "
                f"  (owner_kind IS NULL AND item_id = {marker} AND "
                f"   (session_id = {marker} OR session_id IS NULL))"
                ") "
                "ORDER BY CASE state "
                "  WHEN 'active' THEN 0 "
                "  WHEN 'planned' THEN 1 "
                "  WHEN 'blocked' THEN 2 "
                "END, id DESC LIMIT 1",
                (
                    *_NON_TERMINAL_CLAIM_STATES,
                    item_id, item_id, session_id,
                ),
            ).fetchone()
        except db_backend.database_error_types(conn):
            return None
    if row is None:
        return None

    claim_id = int(row[0] if not hasattr(row, "keys") else row["id"])
    item_id = row[1] if not hasattr(row, "keys") else row["item_id"]
    integration_target = str(
        row[2] if not hasattr(row, "keys") else row["integration_target"]
    )
    state = str(row[3] if not hasattr(row, "keys") else row["state"])

    covered = _covered_paths_for_claim(conn, claim_id)
    paths = _paths_for_item(conn, item_id) if item_id else {}

    return {
        "id": claim_id,
        "item_id": _coerce_int(item_id),
        "integration_target": integration_target,
        "state": state,
        "covered_paths": covered,
        "item_type": paths.get("item_type", ""),
        "worktree_path": paths.get("worktree_path"),
        "project_repo_path": paths.get("project_repo_path"),
        "chain_worktrees": paths.get("chain_worktrees", ()),
    }


def _current_item_for_session(
    conn: Any, session_id: str
) -> Optional[int]:
    try:
        row = conn.execute(
            f"SELECT current_item_id FROM harness_sessions WHERE session_id = {_p(conn)}",
            (session_id,),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return None
    if row is None:
        return None
    raw = row[0] if not hasattr(row, "keys") else row["current_item_id"]
    return _coerce_int(raw)


def _covered_paths_for_claim(
    conn: Any, claim_id: int
) -> List[str]:
    try:
        rows = conn.execute(
            "SELECT pt.path_string FROM path_claim_targets pct "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            f"WHERE pct.claim_id = {_p(conn)} "
            "ORDER BY pct.id",
            (claim_id,),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return []
    return [str(r[0]) for r in rows]


def _paths_for_item(
    conn: Any, item_id: Any,
) -> Dict[str, Any]:
    """Return item metadata used to bind path-claims to physical roots."""
    parsed = _coerce_int(item_id)
    if parsed is None:
        return {}
    try:
        row = conn.execute(
            "SELECT i.type, i.worktree, i.project_id FROM items i "
            f"WHERE i.id = {_p(conn)} LIMIT 1",
            (parsed,),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return {}
    if row is None:
        return {}
    if hasattr(row, "keys"):
        item_type, items_wt, project_id = row["type"], row["worktree"], row["project_id"]
    else:
        item_type, items_wt, project_id = row[0], row[1], row[2]
    item_type_str = str(item_type or "")
    checkout = checkout_for_project_id(_coerce_int(project_id))
    repo_str = str(checkout) if checkout is not None else None
    out: Dict[str, Any] = {
        "item_type": item_type_str,
        "project_repo_path": repo_str,
        "worktree_path": None,
        "chain_worktrees": (),
    }
    if item_type_str == "issue":
        path = item_worktree_path(conn, parsed)
        if path is not None:
            out["worktree_path"] = str(path)
        return out
    if project_id:
        out["chain_worktrees"] = _enumerate_chain_worktrees(
            conn, parsed, _coerce_int(project_id)
        )
    return out


def _enumerate_chain_worktrees(
    conn: Any, epic_id: int, project_id: Optional[int]
) -> Tuple[Tuple[str, str], ...]:
    """Return ``((branch, absolute_path), ...)`` for an epic's chains.

    Each entry's absolute path is the canonical resolved path so the
    ancestor check survives symlinked ``.worktrees`` directories.
    """
    try:
        rows = conn.execute(
            "SELECT worktree FROM epic_dispatch_chains "
            f"WHERE epic_id = {_p(conn)} ORDER BY id",
            (epic_id,),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return ()
    out: List[Tuple[str, str]] = []
    for row in rows:
        branch = row[0] if not hasattr(row, "keys") else row["worktree"]
        branch_str = branch.strip() if isinstance(branch, str) else ""
        if not branch_str:
            continue
        path = worktree_path_for_branch(project_id, branch_str)
        if path is None:
            continue
        try:
            chain_path = path.resolve()
        except OSError:
            continue
        out.append((branch_str, str(chain_path)))
    return tuple(out)


def _pick_chain_for_target(
    target_path: str, chain_worktrees: Tuple[Tuple[str, str], ...]
) -> Optional[str]:
    """Return the chain branch whose absolute path contains target_path."""
    if not target_path or not chain_worktrees or not os.path.isabs(target_path):
        return None
    try:
        target_resolved = Path(target_path).expanduser().resolve()
    except OSError:
        return None
    for branch, chain_abs in chain_worktrees:
        try:
            target_resolved.relative_to(Path(chain_abs).expanduser().resolve())
            return branch
        except (OSError, ValueError):
            continue
    return None


def _resolve_active_worktree(
    conn: Any,
    session_id: str,  # retained for API symmetry; unused for epics
    item_id: Any,
    target_path: str,
) -> Optional[str]:
    """Return the active worktree branch name for this evaluation.

    Path-driven canonical reader. Issue items return ``items.worktree``
    regardless of ``target_path``. Epic items return the chain whose
    worktree path is an ancestor of ``target_path``; ``None`` when no
    chain matches, when the target is missing or non-absolute, or when
    the item has no chains. ``session_id`` is unused — epic worktree
    resolution is driven by the file under examination, not by the
    session row's lane field.
    """
    parsed = _coerce_int(item_id)
    if parsed is None:
        return None
    info = _paths_for_item(conn, parsed)
    if not info:
        return None
    item_type = info.get("item_type", "")
    if item_type == "issue":
        wt = info.get("worktree_path")
        if not wt:
            return None
        return Path(wt).name
    return _pick_chain_for_target(target_path or "", info.get("chain_worktrees", ()))


__all__ = [
    "resolve_active_claim_for_session",
]

"""DB-side resolution of the active path claim for a hook session.

Both Edit/Write and Bash guards consume
:func:`resolve_active_claim_for_session` to find the claim attached to
the current session (or, fallback, the session's current item).

Resolution prefers typed ownership; the registering session is
provenance only and is never authority.

Resolution first checks session-owned non-terminal claims, then item-owned
claims for ``harness_sessions.current_item_id``. Registering-session fields
are provenance and never narrow typed item ownership.

The returned dict carries ``covered_paths``, ``worktree_path`` for a
single lane, and ``chain_worktrees`` for task-lane workflows.

:func:`_resolve_active_worktree` is the path-driven canonical reader
for "which worktree branch is this target bound to for this item?".
Universal lane records are authoritative; single-lane items return their
one branch, while multi-lane items return the lane whose path is an ancestor
of the inbound ``target_path``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.project_checkout_locations import (
    checkout_for_project_id,
)
from yoke_core.domain.path_claim_item_worktree_paths import (
    universal_item_worktree_paths,
)
from yoke_core.domain.path_claim_task_active_scope import (
    effective_targets_for_claim_session,
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
    target_path: str = "",
    cwd: str = "",
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
        return _resolve_active_claim(
            conn,
            session_id=session_id,
            target_path=target_path,
            cwd=cwd,
        )
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _resolve_active_claim(
    conn: Any,
    *,
    session_id: str,
    target_path: str = "",
    cwd: str = "",
) -> Optional[Dict[str, Any]]:
    """DB-side resolution; safe against missing tables (returns None).

    Matches only through the declared typed owner.
    """
    marker = _p(conn)
    placeholders = ",".join(marker for _ in _NON_TERMINAL_CLAIM_STATES)
    # Step 1: session-owned claims.
    try:
        row = conn.execute(
            "SELECT id, owner_item_id AS item_id, integration_target, state "
            "FROM path_claims "
            f"WHERE state IN ({placeholders}) "
            f"AND owner_kind = 'session' AND owner_session_id = {marker} "
            "ORDER BY CASE state "
            "  WHEN 'active' THEN 0 "
            "  WHEN 'planned' THEN 1 "
            "  WHEN 'blocked' THEN 2 "
            "END, id DESC LIMIT 1",
            (*_NON_TERMINAL_CLAIM_STATES, session_id),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return None
    if row is None:
        item_id = _current_item_for_session(conn, session_id)
        if item_id is None:
            return None
        # Step 2: item-owned claims on the session's current item.
        try:
            row = conn.execute(
                "SELECT id, owner_item_id AS item_id, integration_target, state "
                "FROM path_claims "
                f"WHERE state IN ({placeholders}) "
                f"AND owner_kind = 'item' AND owner_item_id = {marker} "
                "ORDER BY CASE state "
                "  WHEN 'active' THEN 0 "
                "  WHEN 'planned' THEN 1 "
                "  WHEN 'blocked' THEN 2 "
                "END, id DESC LIMIT 1",
                (
                    *_NON_TERMINAL_CLAIM_STATES,
                    item_id,
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

    parsed_item_id = _coerce_int(item_id)
    public_ref = (
        render_item_ref(conn, parsed_item_id)
        if parsed_item_id is not None
        else None
    )
    covered_targets = _covered_targets_for_claim(conn, claim_id)
    if parsed_item_id is not None:
        covered_targets = effective_targets_for_claim_session(
            conn,
            item_id=parsed_item_id,
            session_id=session_id,
            target_path=target_path,
            cwd=cwd,
            parent_targets=covered_targets,
        )
    paths = _paths_for_item(conn, item_id) if item_id else {}

    return {
        "id": claim_id,
        "item_id": parsed_item_id,
        "public_ref": public_ref,
        "integration_target": integration_target,
        "state": state,
        "covered_paths": [path for path, _kind in covered_targets],
        "covered_target_kinds": covered_targets,
        "task_lanes": paths.get("task_lanes", False),
        "worktree_path": paths.get("worktree_path"),
        "project_repo_path": paths.get("project_repo_path"),
        "chain_worktrees": paths.get("chain_worktrees", ()),
    }


def _current_item_for_session(conn: Any, session_id: str) -> Optional[int]:
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


def _covered_targets_for_claim(
    conn: Any,
    claim_id: int,
) -> List[Tuple[str, str]]:
    try:
        rows = conn.execute(
            "SELECT pt.path_string, pt.kind FROM path_claim_targets pct "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            f"WHERE pct.claim_id = {_p(conn)} "
            "ORDER BY pct.id",
            (claim_id,),
        ).fetchall()
    except db_backend.database_error_types(conn):
        return []
    return [(str(r[0]), str(r[1])) for r in rows]


def _paths_for_item(
    conn: Any,
    item_id: Any,
) -> Dict[str, Any]:
    """Return item metadata used to bind path-claims to physical roots."""
    parsed = _coerce_int(item_id)
    if parsed is None:
        return {}
    try:
        row = conn.execute(
            f"SELECT i.project_id FROM items i WHERE i.id = {_p(conn)} LIMIT 1",
            (parsed,),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return {}
    if row is None:
        return {}
    if hasattr(row, "keys"):
        project_id = row["project_id"]
    else:
        project_id = row[0]
    checkout = checkout_for_project_id(_coerce_int(project_id))
    repo_str = str(checkout) if checkout is not None else None
    out: Dict[str, Any] = {
        "task_lanes": False,
        "project_repo_path": repo_str,
        "worktree_branch": None,
        "worktree_path": None,
        "chain_worktrees": (),
    }
    universal = universal_item_worktree_paths(
        conn,
        item_id=parsed,
        project_id=_coerce_int(project_id),
    )
    if universal:
        out.update(universal)
    return out


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

    Path-driven canonical reader. Single-lane items return their universal
    branch regardless of ``target_path``. Multi-lane items return the lane
    whose worktree path is an ancestor of ``target_path``; ``None`` when no
    lane matches, when the target is missing or non-absolute, or when
    the item has no lanes. ``session_id`` is unused — multi-lane worktree
    resolution is driven by the file under examination, not by the
    session row's lane field.
    """
    parsed = _coerce_int(item_id)
    if parsed is None:
        return None
    info = _paths_for_item(conn, parsed)
    if not info:
        return None
    if not info.get("task_lanes", False):
        branch = info.get("worktree_branch")
        return str(branch) if branch else None
    return _pick_chain_for_target(target_path or "", info.get("chain_worktrees", ()))


__all__ = ["resolve_active_claim_for_session"]

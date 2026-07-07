"""Planning-phase carve-out for the Bash path-claim parser.

The Bash guard's coverage check denies any non-tmp redirect when the
calling session's active path claim has no worktree binding
(``items.worktree`` empty) and the target is not in the claim's covered
roots — the canonical ``worktree-unresolved`` denial. That posture is
correct for implementation-phase sessions but wrong for planning
sessions (``/yoke idea``, ``/yoke refine``, ``/yoke shepherd``,
``/yoke plan``, ``/yoke freeze``, ``/yoke thaw``) whose item is
pre-implementation by design — those sessions never bind a worktree and
their canonical scratch target is the helper-resolved
``project_scratch_dir.dispatch_inputs_dir(...)`` tree.

This widener consults the session's current item lifecycle status and
drops any parser-extracted mutation whose target is in the planning
scratch subtree when the item is pre-implementation. Implementation-
phase sessions, ambiguous parser tuples, and non-scratch writes are
untouched — the worktree-binding / coverage check fires for them as
before.

Public surface: :data:`PLANNING_SCRATCH_ROOTS`,
:func:`is_planning_scratch_path`,
:func:`planning_scratch_roots`,
:func:`session_is_planning_phase`,
:func:`drop_planning_scratch_mutations`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain import db_backend, project_scratch_dir
from yoke_core.domain.lifecycle_progression import PRE_IMPLEMENTATION_STATUSES
from yoke_core.domain.path_claim_bash_parser import Mutation


# Retained for callers that import the public marker. Runtime roots are
# helper-resolved by :func:`planning_scratch_roots` so environment and
# project changes are reflected per call.
PLANNING_SCRATCH_ROOTS = (
    "project_scratch_dir.dispatch_inputs_dir",
)


# Sentinels emitted by the parser that must never be filtered — the
# guard relies on seeing them to fail-closed or record audit evidence.
_PROTECTED_VERBS = frozenset({"ambiguous", "suppressed"})


def _normalise(path: str) -> str:
    """Return a forward-slash form with leading ``./`` stripped."""
    if not path:
        return ""
    cleaned = path.strip().replace(os.sep, "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _relative_segment_match(path: str, root: str) -> bool:
    """Return True when ``root`` is a path-segment prefix of ``path``."""
    if not path or not root:
        return False
    if path == root:
        return True
    return path.startswith(root.rstrip("/") + "/")


def _absolute_for_match(path: str) -> str:
    """Return an absolute forward-slash path without requiring existence."""
    try:
        return Path(path).expanduser().resolve(strict=False).as_posix()
    except (OSError, RuntimeError, ValueError):
        return _normalise(path)


def planning_scratch_roots() -> tuple[str, ...]:
    """Return helper-resolved planning scratch roots.

    The dispatch-inputs helper owns the scratch root contract
    (``YOKE_SCRATCH_ROOT``, machine config, or OS-temp fallback, with
    project/session/run segments). If that helper cannot resolve a writable
    root, fail closed by returning no planning scratch roots.
    """
    try:
        root = project_scratch_dir.dispatch_inputs_dir(create=False)
    except project_scratch_dir.ScratchRootResolutionError:
        return ()
    return (_absolute_for_match(str(root)),)


def is_planning_scratch_path(target_path: str) -> bool:
    """Return True when ``target_path`` lives under a planning scratch root.

    Only helper-resolved scratch locations are considered planning scratch.
    Retired repo-local scratch paths deliberately return ``False`` so they flow
    through the normal path-claim gate.
    """
    norm = _absolute_for_match(target_path)
    if not norm:
        return False
    for root in planning_scratch_roots():
        croot = _normalise(root)
        if not croot:
            continue
        if _relative_segment_match(norm, croot):
            return True
    return False


def _session_item_status(
    session_id: str,
    *,
    conn: Optional[Any] = None,
) -> Optional[str]:
    """Return the lifecycle status of the session's current item, or None.

    When ``conn`` is omitted, opens a fresh connection via the shared
    ``db_helpers.connect()`` helper. The helper's return value may be a
    raw ``Any`` or a context-manager wrapper depending on
    the caller's patch — both shapes are handled.
    """
    if not session_id:
        return None
    if conn is not None:
        return _query_status(conn, session_id)
    try:
        from yoke_core.domain import db_helpers
    except ImportError:
        return None
    try:
        opened = db_helpers.connect()
    except Exception:
        return None
    if hasattr(opened, "__enter__"):
        try:
            with opened as inner:
                return _query_status(inner, session_id)
        except Exception:
            return None
    try:
        return _query_status(opened, session_id)
    finally:
        try:
            opened.close()
        except Exception:
            pass


def _query_status(conn: Any, session_id: str) -> Optional[str]:
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT i.status FROM harness_sessions hs "
            "JOIN items i ON i.id = hs.current_item_id "
            f"WHERE hs.session_id = {p} LIMIT 1",
            (session_id,),
        ).fetchone()
    except db_backend.database_error_types(conn):
        return None
    except (db_backend.database_error_types(conn) + (AttributeError,)):
        return None
    if row is None:
        return None
    return str(row[0] if not hasattr(row, "keys") else row["status"])


def session_is_planning_phase(
    *,
    session_id: Optional[str],
    conn: Optional[Any] = None,
) -> bool:
    """Return True when the session's current item is pre-implementation.

    Returns False (no widening) when the session id is empty, the
    session has no current item, the DB lookup fails, or the status is
    not in :data:`PRE_IMPLEMENTATION_STATUSES`. Failing closed here is
    intentional — the carve-out must be opt-in via a verifiable signal,
    not the absence of one.
    """
    if not session_id:
        return False
    status = _session_item_status(session_id, conn=conn)
    if not status:
        return False
    return status in PRE_IMPLEMENTATION_STATUSES


def drop_planning_scratch_mutations(
    mutations: List[Mutation],
    *,
    session_id: Optional[str] = None,
    conn: Optional[Any] = None,
) -> List[Mutation]:
    """Filter parser mutations through the planning-phase carve-out.

    Returns ``mutations`` unchanged when no scratch-targeting mutation
    is present, when the session id is missing, or when the session's
    current item is not in a pre-implementation lifecycle status. When
    the carve-out applies, drops only the scratch-targeting mutations
    and preserves every other entry — including ``ambiguous`` and
    ``suppressed`` sentinels the guard relies on.

    Session id resolution: explicit ``session_id`` argument first, then
    ``$YOKE_SESSION_ID``. Empty / missing session id disables the
    carve-out (no widening).
    """
    if not mutations:
        return mutations
    scratch_indices = [
        i for i, mut in enumerate(mutations)
        if mut.verb not in _PROTECTED_VERBS
        and is_planning_scratch_path(mut.target_path)
    ]
    if not scratch_indices:
        return mutations
    sid = (session_id or os.environ.get("YOKE_SESSION_ID", "")).strip()
    if not sid:
        return mutations
    if not session_is_planning_phase(session_id=sid, conn=conn):
        return mutations
    drop = set(scratch_indices)
    return [mut for i, mut in enumerate(mutations) if i not in drop]


__all__ = [
    "PLANNING_SCRATCH_ROOTS",
    "drop_planning_scratch_mutations",
    "is_planning_scratch_path",
    "planning_scratch_roots",
    "session_is_planning_phase",
]

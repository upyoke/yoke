"""Shared worktree-invariant helpers for path-claim and session-cwd guards.

This module is a SHARED HELPER ONLY. It returns structured facts about the
active worktree-scoped item / session, the expected worktree root, the
current harness cwd, and whether ``runtime.api`` resolves under the
expected worktree path. Policy decisions (deny payload, suppression
handling, orientation rendering) live in the consumers:

* :mod:`yoke_core.domain.path_claim_bash_guard` — Bash-command file-mutation
  policy (epic task 4).
* :mod:`yoke_core.domain.lint_session_cwd` — session cwd binding policy
  (epic task 13).
* :mod:`yoke_core.domain.check_path_claim_coverage_at_commit` — pre-commit
  path-claim coverage gate (epic task 14).

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
from yoke_core.domain.denial_field_note_footer import append_field_note_footer


_SESSION_ENV_VARS = (
    "YOKE_SESSION_ID",
    "CLAUDE_SESSION_ID",
    "CODEX_THREAD_ID",
)


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


@dataclass(frozen=True)
class ImportRootVerdict:
    """Outcome of the ``runtime.api`` import-root verification.

    ``ok`` is True when the loaded ``runtime.api`` package resolves under
    the expected worktree path. The verdict is consumed by the
    session-cwd guard (epic task 13) which formats the deny payload.
    """

    ok: bool
    loaded_from: Optional[str]
    expected_under: str
    reason: str


def _resolve_session_id() -> str:
    """Return the first non-empty session id env var, or ``""``."""
    for var in _SESSION_ENV_VARS:
        value = os.environ.get(var) or ""
        if value:
            return value
    return ""


def _normalize_item_id(raw: object) -> Optional[int]:
    """Return ``raw`` as a bare int, stripping a ``YOK-`` prefix if present."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.upper().startswith("YOK-"):
        text = text[4:]
    text = text.lstrip("0") or "0"
    try:
        return int(text)
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
    except db_backend.database_error_types(conn):
        return None
    if row is None:
        return None
    raw = row["current_item_id"] if hasattr(row, "keys") else row[0]
    return _normalize_item_id(raw)


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


def expected_worktree_path(main_root: str, item_id: int) -> str:
    """Return the canonical worktree path for *item_id* under *main_root*.

    The branch convention is ``YOK-N`` followed by an optional
    ``-<slug>`` suffix; this helper returns the base ``YOK-N`` directory
    inside ``.worktrees/`` — callers that need slug-aware matching should
    use prefix comparisons against the result.
    """
    return str(Path(main_root) / ".worktrees" / f"YOK-{int(item_id)}")


def _branch_for_item(item_id: Optional[int]) -> Optional[str]:
    if item_id is None:
        return None
    return f"YOK-{int(item_id)}"


def _resolve_current_item(
    conn: Optional[Any], session_id: str
) -> Optional[int]:
    """Look up the session's current_item_id, opening a connection if needed."""
    if conn is not None:
        return _fetch_current_item_id(conn, session_id)
    try:
        from yoke_core.domain import db_helpers
    except ImportError:
        return None
    try:
        opened = db_helpers.connect()
    except Exception:
        return None
    try:
        return _fetch_current_item_id(opened, session_id)
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
    item_id = _resolve_current_item(conn, sid)
    branch = _branch_for_item(item_id)
    expected_root: Optional[str] = None
    if main_root and item_id is not None:
        expected_root = expected_worktree_path(main_root, item_id)
    return WorktreeInvariantContext(
        session_id=sid,
        item_id=item_id,
        worktree_branch=branch,
        expected_worktree_root=expected_root,
        actual_cwd=str(Path(actual).resolve()),
        is_inside_worktree=is_inside,
    )


def verify_runtime_api_import_root(
    expected_worktree: Path,
) -> ImportRootVerdict:
    """Verify ``runtime.api`` resolves under *expected_worktree*.

    The helper inspects the ``runtime.api`` package's ``__file__`` to
    confirm the loaded module came from the expected worktree path
    rather than a stale main-checkout install. Used by the session-cwd
    guard (epic task 13) to detect cases where a session was launched
    from a worktree but ``PYTHONPATH`` / package install resolution
    still points at main.
    """
    expected_str = str(expected_worktree.resolve())
    try:
        import runtime.api as runtime_api  # noqa: F401
    except ImportError as exc:
        return ImportRootVerdict(
            ok=False,
            loaded_from=None,
            expected_under=expected_str,
            reason=f"could not import runtime.api: {exc!s}",
        )
    loaded_from = getattr(runtime_api, "__file__", None)
    if not loaded_from:
        # Namespace package or otherwise file-less; conservative pass.
        return ImportRootVerdict(
            ok=True,
            loaded_from=None,
            expected_under=expected_str,
            reason="runtime.api has no __file__ (namespace package); skipped",
        )
    resolved_loaded = str(Path(loaded_from).resolve())
    if (
        resolved_loaded.startswith(expected_str + os.sep)
        or resolved_loaded == expected_str
    ):
        return ImportRootVerdict(
            ok=True,
            loaded_from=resolved_loaded,
            expected_under=expected_str,
            reason="runtime.api loaded from expected worktree",
        )
    return ImportRootVerdict(
        ok=False,
        loaded_from=resolved_loaded,
        expected_under=expected_str,
        reason=append_field_note_footer(
            (
                f"runtime.api loaded from {resolved_loaded!r}; "
                f"expected a path under {expected_str!r}. The session's "
                "PYTHONPATH or installed package is anchored outside the "
                "active worktree."
            ),
            rule_id="lint-worktree-path-invariants",
        ),
    )


__all__ = [
    "ImportRootVerdict",
    "WorktreeInvariantContext",
    "expected_worktree_path",
    "resolve_active_worktree_context",
    "verify_runtime_api_import_root",
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

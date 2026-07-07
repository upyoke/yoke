"""Structural backstop: refuse pytest invocations from outside the
session's claim-bound worktree.

This is the read/test-path counterpart to ``yoke_core.domain.lint_session_cwd``,
which validates write targets against the active claim. The lint catches
Edit/Write/Read writes that would leak across worktrees, but pytest's
positional collection path is a *read* operation that resolves against
the harness's cwd at invocation time — when sticky cwd stayed at main
because no explicit ``cd`` was performed after worktree provisioning,
pytest silently collects from the main tree and the agent never sees
that the worktree's tests/fixes weren't exercised.

The check below fires only when ALL three signals line up:

1. ``YOKE_SESSION_ID`` is present in the environment.
2. The session holds at least one active ``work_claims`` row whose
   ``items.worktree`` branch resolves to an absolute worktree path
   (see :mod:`yoke_core.domain.session_claimed_worktrees`).
3. The current cwd is outside every claimed worktree AND outside the
   free-path allowlist (``/tmp``, ``/var/folders/...``).

When all three hold, the helper returns a remediation string naming the
first claimed worktree. ``watch_pytest`` prints it and exits non-zero
before invoking pytest. Any DB / import error fails open (returns
``None``) so test environments without a Yoke DB schema (CI fixtures,
unrelated installs) are not blocked.

The free-path allowlist is read from
:data:`yoke_core.domain.lint_session_cwd_validate.FREE_PATH_PREFIXES`
so the read/test backstop and the write lint agree on which temp
directories pass through unconditionally.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Sequence


WORKTREE_BINDING_REFUSAL_TEMPLATE = (
    "watch_pytest WORKTREE-BINDING REFUSAL: session {sid} holds an active "
    "work-claim with worktree '{wt}', but cwd ({cwd}) is outside that "
    "worktree. pytest's positional collection path resolves from cwd, so "
    "running from main would silently exercise the wrong tree.\n"
    "To run tests from the claimed worktree:\n"
    "  cd \"{wt}\"\n"
    "and re-run watch_pytest."
)


def _is_inside(target: str, root: str) -> bool:
    if not target or not root:
        return False
    try:
        t = str(Path(target).resolve())
        r = str(Path(root).resolve())
    except OSError:
        return False
    if t == r:
        return True
    return t.startswith(r + os.sep)


def _cwd_is_free(cwd: str) -> bool:
    try:
        from yoke_core.domain.lint_session_cwd_validate import (
            FREE_PATH_PREFIXES,
        )
    except Exception:
        return False
    try:
        resolved = str(Path(cwd).resolve())
    except OSError:
        return False
    for prefix in FREE_PATH_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            return True
    return False


def evaluate_worktree_binding(
    cwd: str, session_id: str, claim_worktrees: Sequence[str],
) -> Optional[str]:
    """Pure evaluation — return a remediation string or ``None``.

    Pass-through (returns ``None``) for the same situations the write
    lint allows: empty session id, no claim-bound worktrees, cwd under
    the free-path allowlist, or cwd inside any claimed worktree.
    """
    if not session_id:
        return None
    worktrees = [w for w in claim_worktrees if w]
    if not worktrees:
        return None
    if _cwd_is_free(cwd):
        return None
    for wt in worktrees:
        if _is_inside(cwd, wt):
            return None
    return WORKTREE_BINDING_REFUSAL_TEMPLATE.format(
        sid=session_id, wt=worktrees[0], cwd=cwd,
    )


def resolve_claim_worktrees(session_id: str) -> Sequence[str]:
    """Open the canonical DB and return the session's claim worktree paths.

    Any error (no DB, schema mismatch, import failure) returns ``[]`` so
    the backstop fails open. The canonical DB resolver
    (``yoke_core.domain.db_helpers.connect``) is the same one
    ``lint_session_cwd`` uses — the backstop and the write lint share
    the same claim view.
    """
    if not session_id:
        return []
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.session_claimed_worktrees import (
            claimed_worktrees,
        )
        with db_helpers.connect() as conn:
            claims = list(claimed_worktrees(conn, session_id=session_id))
    except Exception:
        return []
    return [c.worktree_path for c in claims if c.worktree_path]


def check() -> Optional[str]:
    """Top-level entry point. Reads env + cwd; returns refusal or ``None``."""
    session_id = os.environ.get("YOKE_SESSION_ID", "").strip()
    if not session_id:
        return None
    worktrees = resolve_claim_worktrees(session_id)
    if not worktrees:
        return None
    return evaluate_worktree_binding(os.getcwd(), session_id, worktrees)


__all__ = [
    "WORKTREE_BINDING_REFUSAL_TEMPLATE",
    "evaluate_worktree_binding",
    "resolve_claim_worktrees",
    "check",
]

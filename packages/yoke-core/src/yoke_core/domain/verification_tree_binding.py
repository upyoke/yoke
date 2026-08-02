"""Bind verification runs to the session's claim-bound worktree.

A verification run answers "does this tree pass?" — but until the tree is
named, a green says nothing about *which* tree passed. Two failure modes
converge here:

1. **Silent drift.** The harness re-applies a prior working directory
   between tool calls, so a session whose claimed lane is a linked
   worktree can find itself invoking pytest from the main checkout with
   no explicit ``cd`` in sight. pytest's positional collection resolves
   against the invocation directory, so the main tree is collected and
   the worktree's changes are never exercised. The existing
   out-of-checkout refusal in :mod:`yoke_core.tools._source_pythonpath`
   does not fire, because main *is* a legitimate checkout — just not the
   claimed one. The write-authority lint
   (:mod:`yoke_core.domain.lint_session_cwd`) does not fire either,
   because a test run is a read.

2. **Indistinguishable evidence.** A recorded green that carries no tree
   identity cannot be told apart from a green produced against the wrong
   tree, so the drift survives into the audit trail.

This module owns both answers. :func:`evaluate_tree_binding` is the pure
decision — refuse when the session holds claim-bound worktrees and the
run would execute outside all of them — and :func:`resolve_tree_identity`
names a tree by its root and HEAD sha so a run can record what it
actually verified.

Session identity resolves through the canonical ambient chain
(:mod:`yoke_core.domain.session_ambient_identity`), not a bare
``YOKE_SESSION_ID`` read: harnesses that publish identity only through
the hook-written process-anchor registry would otherwise pass every
check by default, which is precisely the live configuration the drift
was observed in.

Every integration point fails open. A missing Yoke schema, an
unresolvable session, a checkout with no git metadata — none of these
block a run, because the check exists to catch drift, not to become a
new way for verification to be unavailable.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

#: Wrapper/CLI flag that runs a deliberate cross-tree verification.
ALLOW_TREE_MISMATCH_FLAG = "--allow-tree-mismatch"

TREE_BINDING_REFUSAL_TEMPLATE = (
    "{surface} TREE-BINDING REFUSAL: session {sid} holds an active "
    "work-claim with worktree '{wt}', but this run would execute in "
    "'{tree}', outside that worktree. Verification that runs in the wrong "
    "tree reports a green for code nobody changed.\n"
    "To verify the claimed worktree:\n"
    '  cd "{wt}"\n'
    f"and re-run, or pass {ALLOW_TREE_MISMATCH_FLAG} for a deliberate "
    "cross-tree run."
)

ALLOW_TREE_MISMATCH_NOTICE = (
    f"{{surface}}: {ALLOW_TREE_MISMATCH_FLAG} — verifying '{{tree}}' while "
    "the claimed worktree is '{wt}'."
)


@dataclass(frozen=True)
class TreeIdentity:
    """Which tree a verification run executed against."""

    root: str
    head_sha: str

    def as_payload(self) -> dict[str, str]:
        """Serialize for evidence sections and QA run records."""
        return {"root": self.root, "head_sha": self.head_sha}


def _is_inside(target: str, root: str) -> bool:
    if not target or not root:
        return False
    try:
        resolved_target = str(Path(target).resolve())
        resolved_root = str(Path(root).resolve())
    except OSError:
        return False
    if resolved_target == resolved_root:
        return True
    return resolved_target.startswith(resolved_root + os.sep)


def _tree_is_free(tree: str) -> bool:
    """True when *tree* sits under the write lint's free-path allowlist.

    Read from :mod:`yoke_core.domain.lint_session_cwd_validate` so the
    verification backstop and the write lint agree on which temp
    directories pass through unconditionally.
    """
    try:
        from yoke_core.domain.lint_session_cwd_validate import (
            FREE_PATH_PREFIXES,
        )
    except Exception:
        return False
    try:
        resolved = str(Path(tree).resolve())
    except OSError:
        return False
    for prefix in FREE_PATH_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            return True
    return False


def evaluate_tree_binding(
    tree: str,
    session_id: str,
    claim_worktrees: Sequence[str],
    *,
    surface: str,
) -> Optional[str]:
    """Pure decision — a remediation string, or ``None`` to proceed.

    Passes through for an empty session id, a session with no
    claim-bound worktrees (inline ``/yoke`` skill work and main-checkout
    source-dev both land here), a tree under the free-path allowlist, or
    a tree inside any claimed worktree.
    """
    if not session_id:
        return None
    worktrees = [str(path) for path in claim_worktrees if str(path).strip()]
    if not worktrees:
        return None
    if _tree_is_free(tree):
        return None
    for worktree in worktrees:
        if _is_inside(tree, worktree):
            return None
    return TREE_BINDING_REFUSAL_TEMPLATE.format(
        surface=surface, sid=session_id, wt=worktrees[0], tree=tree,
    )


def resolve_claim_worktrees(session_id: str) -> Sequence[str]:
    """Worktree paths this session holds through active work claims.

    Any error (no DB, schema mismatch, import failure) returns ``[]`` so
    the backstop fails open. Shares the claim view with the write lint
    through :mod:`yoke_core.domain.session_claimed_worktrees`.
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
    return [claim.worktree_path for claim in claims if claim.worktree_path]


def ambient_session_id() -> str:
    """The calling process's session id through the canonical chain.

    Env chain first, then the hook-written process-anchor registry. A
    bare ``YOKE_SESSION_ID`` read would miss every harness that publishes
    identity only through the registry.
    """
    try:
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        return (resolve_ambient_session_id() or "").strip()
    except Exception:
        return ""


def check(*, surface: str, tree: Optional[str] = None) -> Optional[str]:
    """Resolve session and claims, then evaluate *tree* (default: cwd)."""
    session_id = ambient_session_id()
    if not session_id:
        return None
    worktrees = resolve_claim_worktrees(session_id)
    if not worktrees:
        return None
    target = tree if tree is not None else os.getcwd()
    return evaluate_tree_binding(
        target, session_id, worktrees, surface=surface,
    )


def mismatch_notice(*, surface: str, tree: Optional[str] = None) -> Optional[str]:
    """One line naming the cross-tree run an override is about to allow.

    Returns ``None`` when the run is bound to its claimed worktree, so an
    override that changes nothing stays silent.
    """
    session_id = ambient_session_id()
    if not session_id:
        return None
    worktrees = resolve_claim_worktrees(session_id)
    if not worktrees:
        return None
    target = tree if tree is not None else os.getcwd()
    if evaluate_tree_binding(
        target, session_id, worktrees, surface=surface,
    ) is None:
        return None
    return ALLOW_TREE_MISMATCH_NOTICE.format(
        surface=surface, tree=target, wt=worktrees[0],
    )


def _git(args: Sequence[str], cwd: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def resolve_tree_identity(start: Optional[str | Path] = None) -> Optional[TreeIdentity]:
    """Name the tree at *start* by its root and HEAD sha.

    Returns ``None`` when *start* is not inside a git worktree or has no
    commits yet — a caller recording evidence should then say so rather
    than invent an identity.
    """
    cwd = str(Path(start).resolve()) if start is not None else os.getcwd()
    if not Path(cwd).is_dir():
        return None
    root = _git(["rev-parse", "--show-toplevel"], cwd)
    if root is None:
        return None
    head = _git(["rev-parse", "HEAD"], cwd)
    if head is None:
        return None
    return TreeIdentity(root=root, head_sha=head)


__all__ = [
    "ALLOW_TREE_MISMATCH_FLAG",
    "ALLOW_TREE_MISMATCH_NOTICE",
    "TREE_BINDING_REFUSAL_TEMPLATE",
    "TreeIdentity",
    "ambient_session_id",
    "check",
    "evaluate_tree_binding",
    "mismatch_notice",
    "resolve_claim_worktrees",
    "resolve_tree_identity",
]

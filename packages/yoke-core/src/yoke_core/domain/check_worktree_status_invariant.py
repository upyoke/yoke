"""Worktree-status pre-commit invariant.

When the current branch is an item lane branch (its public ref
``PREFIX-N`` or a recorded lane branch, in any project), the owning item's ``status`` MUST be in the implementation-phase set:

- ``implementing`` — active code-writing.
- ``reviewing-implementation`` — self-review and fix loop.
- ``polishing-implementation`` — owned by ``/yoke polish``.

Committing on a lane branch while the item is still ``refined-idea``
(or anything past ``polishing-implementation``) is a procedural miss:
the implementation-entry transition was skipped, or polish/usher already
moved the item beyond commit-eligible. The guard refuses the commit and
points at ``/yoke implement YOK-N`` to enter the implementation lane.

This closes the procedural gap where a worktree branch can receive
commits before the item enters an implementation-owned status, or after
the implementation phase has already handed off.

Behaviour:

- DB path unresolvable or DB unreachable → skip (do not block on
  environment issues).
- Branch names no item lane → skip (commits on main, a branch without a
  work item, or an exploratory ``PREFIX-N`` branch with no item). The
  number in ``PREFIX-N`` is a project sequence, never ``items.id``.
- Status in the allowed set → pass.
- Status not in the allowed set → block with remediation.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.item_worktree_resolution import item_id_for_lane_name
from yoke_core.domain.project_identity import render_item_ref

# the items.blocked flag is a routing/dispatch hold and does NOT
# affect this pre-commit check. An item already in a worktree may keep
# committing while items.blocked=1; the gate only refuses the next forward
# transition. See yoke_core.domain.advance_blocked_gate for that gate.
ALLOWED_IMPLEMENTATION_STATUSES = frozenset({
    "implementing",
    "reviewing-implementation",
    "polishing-implementation",
})


@dataclass
class WorktreeStatusVerdict:
    """Outcome of the pre-commit worktree-status check.

    Attributes:
        ok: True when the commit should be allowed.
        skipped: True when the check did not apply (branch doesn't match,
            no DB row, DB unreachable). ``ok`` is True in this case too.
        skip_reason: Human-readable reason when ``skipped``.
        item_id: Owning ``items.id`` when the branch names an item lane.
        observed_status: Current status when looked up.
        message: Block message when ``ok`` is False; empty otherwise.
    """

    ok: bool
    skipped: bool = False
    skip_reason: str = ""
    item_id: Optional[int] = None
    observed_status: Optional[str] = None
    message: str = ""


def _current_branch() -> Optional[str]:
    """Return the current branch's short ref name, or None if unknown."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return name or None


def _format_block(public_ref: str, observed: str) -> str:
    return (
        f"ERROR: cannot commit on worktree branch {public_ref} while "
        f"items.status is '{observed}'.\n"
        f"\n"
        f"Allowed statuses for a worktree-branch commit: "
        f"{', '.join(sorted(ALLOWED_IMPLEMENTATION_STATUSES))}.\n"
        f"\n"
        f"Likely root cause: the implementation-entry skill never ran the "
        f"refined-idea -> implementing transition, or polish/usher "
        f"already moved the item past polishing-implementation.\n"
        f"\n"
        f"Remediation:\n"
        f"  - From refined-idea: run `/yoke implement {public_ref}` to "
        f"drive the proper transition.\n"
        f"  - From a post-polish status: investigate why a worktree "
        f"commit is being attempted; the implementation phase is over.\n"
    )


def _resolve_db_path_or_none() -> Optional[str]:
    """Best-effort DB path resolver. Returns None when control plane
    cannot be located — the guard skips rather than blocks."""
    env_db = os.environ.get("CANONICAL_YOKE_DB") or os.environ.get("YOKE_DB")
    if env_db:
        return env_db
    try:
        from yoke_core.domain.schema_common import _resolve_db_path
        return _resolve_db_path()
    except Exception:
        return None


def evaluate(*, branch: Optional[str] = None) -> WorktreeStatusVerdict:
    """Run the worktree-status check. ``branch`` defaults to ``HEAD``."""
    if branch is None:
        branch = _current_branch()
    if not branch:
        return WorktreeStatusVerdict(
            ok=True, skipped=True,
            skip_reason="branch not resolvable (detached HEAD?)",
        )
    if branch.startswith("trial/"):
        return WorktreeStatusVerdict(
            ok=True, skipped=True,
            skip_reason=f"branch '{branch}' is a merge-trial ref, not a lane",
        )

    db_path = _resolve_db_path_or_none()
    if db_path is None:
        return WorktreeStatusVerdict(
            ok=True, skipped=True,
            skip_reason="control-plane DB path not resolvable",
        )

    conn = None
    try:
        conn = db_helpers.connect(db_path)
        item_id = item_id_for_lane_name(conn, branch)
        row = None
        public_ref = ""
        if item_id is not None:
            row = conn.execute(
                "SELECT status FROM items WHERE id = %s", (item_id,),
            ).fetchone()
            public_ref = render_item_ref(conn, item_id)
    except db_backend.operational_error_types(conn=conn) + (RuntimeError,):
        return WorktreeStatusVerdict(
            ok=True, skipped=True,
            skip_reason="DB unreachable for read",
        )
    finally:
        if conn is not None:
            conn.close()

    if item_id is None or row is None:
        return WorktreeStatusVerdict(
            ok=True, skipped=True,
            skip_reason=f"branch '{branch}' names no item lane",
        )

    status = row["status"]
    if status in ALLOWED_IMPLEMENTATION_STATUSES:
        return WorktreeStatusVerdict(
            ok=True, item_id=item_id, observed_status=status,
        )

    return WorktreeStatusVerdict(
        ok=False, item_id=item_id, observed_status=status,
        message=_format_block(public_ref, status),
    )


__all__ = [
    "ALLOWED_IMPLEMENTATION_STATUSES",
    "WorktreeStatusVerdict",
    "evaluate",
]

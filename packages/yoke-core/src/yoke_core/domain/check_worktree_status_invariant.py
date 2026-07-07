"""Worktree-status pre-commit invariant.

When the current branch is a Yoke worktree branch (``YOK-N``), the
matching item's ``status`` MUST be in the implementation-phase set:

- ``implementing`` — active code-writing.
- ``reviewing-implementation`` — self-review and fix loop.
- ``polishing-implementation`` — owned by ``/yoke polish``.

Committing on a ``YOK-N`` branch while the item is still ``refined-idea``
(or anything past ``polishing-implementation``) is a procedural miss:
the agent skipped advance's status flip, or polish/usher already moved
the item beyond commit-eligible. The guard refuses the commit and
points at ``/yoke advance YOK-N implementation`` (or ``--no-verify``
as the documented operator escape hatch).

This closes the procedural gap where a worktree branch can receive
commits before the item enters an implementation-owned status, or after
the implementation phase has already handed off.

Behaviour:

- Branch doesn't match ``YOK-N`` → skip (commits on main, branch
  without ticket, etc.).
- Item row missing → skip (exploratory ``YOK-N`` branch with no DB
  presence).
- DB unreachable → skip (do not block on environment issues).
- Status in the allowed set → pass.
- Status not in the allowed set → block with remediation.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from yoke_core.domain import db_backend, db_helpers

_YOKE_WORKTREE_BRANCH = re.compile(r"^YOK-(\d+)$")

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
        item_id: Parsed item id when the branch matched.
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


def _format_block(item_id: int, observed: str) -> str:
    return (
        f"ERROR: cannot commit on worktree branch YOK-{item_id} while "
        f"items.status is '{observed}'.\n"
        f"\n"
        f"Allowed statuses for a worktree-branch commit: "
        f"{', '.join(sorted(ALLOWED_IMPLEMENTATION_STATUSES))}.\n"
        f"\n"
        f"Likely root cause: advance's finalize step never ran (the "
        f"refined-idea -> implementing flip was skipped), or polish/usher "
        f"already moved the item past polishing-implementation.\n"
        f"\n"
        f"Remediation:\n"
        f"  - From refined-idea: run `/yoke advance YOK-{item_id} "
        f"implementation` to drive the proper transition.\n"
        f"  - From a post-polish status: investigate why a worktree "
        f"commit is being attempted; the implementation phase is over.\n"
        f"  - Bypass (operator-asserted): `git commit --no-verify`.\n"
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

    match = _YOKE_WORKTREE_BRANCH.match(branch)
    if not match:
        return WorktreeStatusVerdict(
            ok=True, skipped=True,
            skip_reason=f"branch '{branch}' is not a YOK-N worktree branch",
        )

    item_id = int(match.group(1))
    db_path = _resolve_db_path_or_none()
    if db_path is None:
        return WorktreeStatusVerdict(
            ok=True, skipped=True, item_id=item_id,
            skip_reason="control-plane DB path not resolvable",
        )

    conn = None
    try:
        conn = db_helpers.connect(db_path)
        row = conn.execute(
            "SELECT status FROM items WHERE id = %s", (item_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn=conn) + (RuntimeError,):
        return WorktreeStatusVerdict(
            ok=True, skipped=True, item_id=item_id,
            skip_reason="DB unreachable for read",
        )
    finally:
        if conn is not None:
            conn.close()

    if row is None:
        return WorktreeStatusVerdict(
            ok=True, skipped=True, item_id=item_id,
            skip_reason=f"no items row for YOK-{item_id}",
        )

    status = row["status"]
    if status in ALLOWED_IMPLEMENTATION_STATUSES:
        return WorktreeStatusVerdict(
            ok=True, item_id=item_id, observed_status=status,
        )

    return WorktreeStatusVerdict(
        ok=False, item_id=item_id, observed_status=status,
        message=_format_block(item_id, status),
    )


__all__ = [
    "ALLOWED_IMPLEMENTATION_STATUSES",
    "WorktreeStatusVerdict",
    "evaluate",
]

"""Work-claim-derived write authority for workspace-anchored writers.

Replaces the prior ``$YOKE_BOUND_WORKSPACE`` env-var anchor with a
**live work-claim** check: the calling harness session may write a
repo-tree file only when the target lands under one of the session's
active worktree work-claims, or the free-path allowlist (``/tmp``,
``/var/folders/...``). Sessions with no worktree claims fall through
to no-op (operator maintenance / test fixtures / orchestrator shape) —
the same posture :mod:`yoke_core.domain.lint_session_cwd_validate`
takes for the no-claims case.

The contrast that matters: ``$YOKE_BOUND_WORKSPACE`` is set once at
SessionStart and goes stale the moment a session rotates claims. The
authority signal here is the live row in ``work_claims`` itself —
the same source the per-tool-call lint consumes. When a session holds
a worktree work-claim but a writer's resolved target lands in main,
this helper raises ``RuntimeError`` before the rename step lands a
wrong-tree write.

The helper is **no-op** when ``$YOKE_SESSION_ID`` is unset (operator
maintenance, test fixtures with no harness session) — preserving the
flexibility the prior env-var helper already had.

Composition rather than duplication: this module imports
:func:`yoke_core.domain.session_claimed_worktrees.claimed_worktrees`
and :data:`yoke_core.domain.lint_session_cwd_validate.FREE_PATH_PREFIXES`
so the work-claim SQL/joins and the free-path allowlist have a single
source of truth shared with the per-tool-call lint.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Sequence

from yoke_core.domain.lint_session_cwd_validate import FREE_PATH_PREFIXES
from yoke_core.domain.session_claimed_worktrees import (
    ClaimedWorktree,
    claimed_worktrees,
)


SESSION_ID_ENV_VAR = "YOKE_SESSION_ID"


def _resolve_session_id(explicit: Optional[str]) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    raw = os.environ.get(SESSION_ID_ENV_VAR, "")
    return raw.strip()


def _resolve_for_display(target: Path) -> str:
    try:
        return str(target.resolve())
    except OSError:
        return str(target)


def _is_inside(target: Path, root: str) -> bool:
    if not root:
        return False
    try:
        t = str(target.resolve())
        r = str(Path(root).resolve())
    except OSError:
        return False
    if t == r:
        return True
    return t.startswith(r + os.sep)


def _is_free_path(target: Path) -> bool:
    candidates = {_resolve_for_display(target)}
    raw = str(target)
    expanded = os.path.expanduser(raw)
    if expanded != raw:
        candidates.add(_resolve_for_display(Path(expanded)))
    for cand in candidates:
        for prefix in FREE_PATH_PREFIXES:
            if cand == prefix or cand.startswith(prefix + os.sep):
                return True
    return False


def _is_planning_scratch_allowed(target: Path, *, session_id: str) -> bool:
    """Planning-phase carve-out for helper-resolved dispatch-inputs scratch.

    Mirrors the Bash-parser widener: when the session's item is in a
    pre-implementation status AND the resolved target lives under the
    helper-resolved planning scratch root, allow the write without requiring
    the target to land under a claimed worktree. Implementation-phase
    sessions and non-scratch targets fall through unchanged.
    """
    from yoke_core.domain.path_claim_bash_parser_planning_phase import (
        is_planning_scratch_path,
        session_is_planning_phase,
    )
    candidates = {_resolve_for_display(target), str(target)}
    if not any(is_planning_scratch_path(cand) for cand in candidates):
        return False
    return session_is_planning_phase(session_id=session_id)


def _format_authority(claims: Sequence[ClaimedWorktree]) -> str:
    return ", ".join(f"worktree={c.worktree_path!r}" for c in claims) or "<none>"


def assert_target_under_session_work_authority(
    target: Path,
    *,
    session_id: Optional[str] = None,
) -> None:
    """Refuse a write target outside the calling session's work-claim authority.

    Resolution order:

    1. Session id is the explicit ``session_id`` argument when supplied;
       otherwise read from ``$YOKE_SESSION_ID``. Empty session id is a
       no-op (operator maintenance / test-fixture path).
    2. Open the control-plane DB via the shared
       :mod:`yoke_core.domain.db_helpers` connector and read the
       session's active worktree claims via
       :func:`session_claimed_worktrees.claimed_worktrees`. Items and
       epic-tasks without a populated worktree branch contribute no row
       (the same filter the per-tool-call lint uses) — sessions with
       only no-worktree claims fall through to no-op.
    3. A session with no worktree claims is the orchestrator /
       maintenance posture — no-op.
    4. With one or more worktree claims, the resolved ``target`` MUST
       land under (a) a claimed worktree's path, or (b) the free-path
       allowlist. Writes to the main control plane (the project repo
       root outside ``.worktrees/``) are refused — that wrong-tree write
       shape is what the helper exists to catch.

    Mismatch raises ``RuntimeError`` naming both the resolved target
    and the session's authority. The error fires before the writer's
    atomic-rename step so a wrong-tree partial file is never left
    behind.
    """
    sid = _resolve_session_id(session_id)
    if not sid:
        return

    from yoke_core.domain import db_helpers
    try:
        with db_helpers.connect() as conn:
            claims = claimed_worktrees(conn, session_id=sid)
    except Exception:
        return

    if not claims:
        return

    target_path = Path(target)

    if _is_free_path(target_path):
        return

    if _is_planning_scratch_allowed(target_path, session_id=sid):
        return

    for claim in claims:
        if claim.worktree_path and _is_inside(target_path, claim.worktree_path):
            return

    raise RuntimeError(
        f"workspace_authority: refusing write to "
        f"{_resolve_for_display(target_path)!r} -- "
        f"session {sid!r} holds {len(claims)} active worktree claim(s) but "
        f"the target is not under any claimed worktree or free path. "
        f"Authorised authorities: {_format_authority(claims)}"
    )


def assert_seed_source_under_target_root(
    seed_module_file: Optional[str],
    target_root: Path,
    *,
    seed_module_name: str,
    session_id: Optional[str] = None,
) -> None:
    """Defense for Coupling B: seed module loaded from wrong tree.

    Python imports ``from yoke_core.domain import X`` resolve at
    module-load time from ``sys.path[0]`` (cwd-derived). When cwd is
    main but ``target_root`` is the worktree, the renderer reads the
    seed from main and writes worktree-named outputs — the on-disk
    content disagrees with what the worktree's source actually says.

    The check fires at write-time (not import-time, because Python's
    import system caches modules — the same process always has one
    bound seed module for its lifetime). When ``seed_module_file`` is
    not under ``target_root.resolve()``, raise ``RuntimeError`` with a
    "seed loaded from X, target is Y" message that is structurally
    distinct from the work-claim authority refusal.

    Gated on ``$YOKE_SESSION_ID`` (or the explicit ``session_id``
    argument) so test fixtures with no harness session get the
    operator-maintenance no-op path. A ``None`` ``seed_module_file``
    (built-in / dynamically created module) is a no-op.
    """
    sid = _resolve_session_id(session_id)
    if not sid:
        return
    if not seed_module_file:
        return
    try:
        seed_path = Path(seed_module_file).resolve()
        root_path = Path(target_root).resolve()
    except OSError:
        return
    if _is_free_path(root_path):
        # Test fixtures intentionally target /tmp or /var/folders with a
        # cwd-imported seed module — the seed-source mismatch is normal.
        return
    # External-project targets (an installed project repo with no Yoke
    # source tree — e.g. board rebuild for Buzz over the machine-installed
    # CLI) legitimately load the seed from the CLI's Yoke checkout, which
    # is never under target_root. Only the worktree-dev hazard warrants the
    # refusal: target_root is itself a Yoke checkout whose seed should
    # come from that tree. Detect the external case — the seed's
    # repo-relative path does not exist under target_root — and allow it.
    seed_parts = seed_path.parts
    if "runtime" in seed_parts:
        seed_rel = Path(*seed_parts[seed_parts.index("runtime"):])
        if not (root_path / seed_rel).exists():
            return
    try:
        seed_path.relative_to(root_path)
    except ValueError:
        raise RuntimeError(
            f"workspace_authority: seed-source mismatch for "
            f"{seed_module_name!r} -- seed loaded from "
            f"{str(seed_path)!r}, target is {str(root_path)!r}. The "
            "imported seed/schema module belongs to a different "
            "checkout than the resolved target_root; the renderer "
            "would write target-named outputs from the wrong tree."
        )


__all__ = [
    "SESSION_ID_ENV_VAR",
    "assert_target_under_session_work_authority",
    "assert_seed_source_under_target_root",
]

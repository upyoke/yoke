"""Shared `(target_path, cwd)` resolver for path-claim guards.

Both :mod:`path_claim_pre_edit_guard` and :mod:`path_claim_bash_guard`
share the same resolution logic — a single implementation prevents the
two guards from drifting on what counts as "in-claim", "out-of-claim",
or "wrong-cwd".

Both ``out-of-claim`` and ``wrong-cwd`` failures emit the canonical
``yoke claims path widen`` command template via :func:`widen_template`.

Active-claim DB lookup is owned by
:mod:`path_claim_active_claim_lookup`; this module is pure logic over
an injected :class:`ClaimContext` plus an optional connection that the
DB-side traversal in :func:`evaluate_target` does not currently read.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Tuple

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.path_claim_active_claim_lookup import (
    _pick_chain_for_target,
)
from yoke_core.domain.path_claim_target_context import ClaimContext, Failure
from yoke_core.domain.path_claim_target_domain import (
    domain_root_for_absolute_target,
    is_free_path_basename_redirect,
    outside_claim_domain,
)


# Failure mode constants — both guards reference these.
OUT_OF_CLAIM = "out-of-claim"
WRONG_CWD = "wrong-cwd"
# Claim has no active universal lane. Narrative
# teaches ``worktree_preflight``, NOT the ``path-claims widen`` template.
WORKTREE_UNRESOLVED = "worktree-unresolved"


def widen_template(
    *,
    claim_id: Optional[int],
    item_id: Optional[int],
    target_path: str,
    public_ref: Optional[str] = None,
) -> str:
    """Return the canonical ``yoke claims path widen`` remediation.

    The template includes the offending path so the operator's next
    action is one mechanical paste.
    """
    cid = claim_id if claim_id is not None else "<claim_id>"
    item = public_ref or (
        format_item_ref(None, None, None, item_id=item_id)
        if item_id is not None
        else "YOK-N"
    )
    return (
        "yoke claims path widen "
        f"--claim-id {cid} --add-paths {target_path} "
        f'--reason "cover target path" --item {item}'
    )


def _make_repo_relative(target_path: str, cwd: str) -> str:
    """Return ``target_path`` as a forward-slash repo-relative string.

    Absolute paths inside ``cwd`` are made relative to ``cwd``. Relative
    paths are returned with leading ``./`` stripped. Outside-cwd
    absolute paths are returned as-is so the caller can decide.
    """
    if not target_path:
        return ""
    cleaned = target_path.strip()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not os.path.isabs(cleaned):
        return cleaned.replace(os.sep, "/")
    try:
        rel = os.path.relpath(cleaned, cwd)
    except ValueError:
        return cleaned.replace(os.sep, "/")
    if rel.startswith(".."):
        return cleaned.replace(os.sep, "/")
    return rel.replace(os.sep, "/")


def _effective_worktree_for(target_path: str, cwd: str, ctx: ClaimContext) -> str:
    """Return the worktree root that binds ``target_path`` under ``ctx``.

    For single-lane items this is ``ctx.worktree_path`` (or empty when none).
    For task-lane items the worktree is chosen by matching ``target_path``
    against ``ctx.chain_worktrees`` — the chain whose absolute path is
    an ancestor of the target wins. Returns ``""`` when nothing matches
    (caller falls through to ``project_repo_path``).
    """
    if ctx.task_lanes and ctx.chain_worktrees:
        candidate = target_path
        if candidate and not os.path.isabs(candidate) and cwd:
            candidate = str(Path(cwd) / candidate)
        branch = _pick_chain_for_target(candidate, ctx.chain_worktrees)
        if not branch:
            return ""
        for b, abs_path in ctx.chain_worktrees:
            if b == branch:
                return abs_path
        return ""
    return ctx.worktree_path or ""


def _path_within_coverage(
    rel_path: str,
    covered: Tuple[str, ...],
    target_kinds: Tuple[Tuple[str, str], ...] = (),
) -> bool:
    """Return True when ``rel_path`` is inside any covered root.

    Coverage roots may be files (exact match) or directories (prefix
    match with a trailing ``/`` boundary so ``runtime/api`` does not
    match ``runtime/api2`` accidentally).
    """
    norm = rel_path.replace(os.sep, "/").lstrip("/")
    kinds = {path: kind for path, kind in target_kinds}
    for root in covered:
        croot = (root or "").strip().replace(os.sep, "/").lstrip("/")
        if not croot:
            continue
        if norm == croot:
            return True
        if (not target_kinds or kinds.get(root) == "directory") and norm.startswith(
            croot.rstrip("/") + "/"
        ):
            return True
    return False


def evaluate_target(
    *,
    target_path: str,
    cwd: str,
    ctx: ClaimContext,
    conn: Optional[Any] = None,  # noqa: ARG001
) -> Optional[Failure]:
    """Decide whether ``target_path`` (in ``cwd``) is allowed by ``ctx``.

    Returns ``None`` on allow; returns a :class:`Failure` on deny. The
    Failure's ``mode`` distinguishes out-of-claim from wrong-cwd so the
    caller can emit the right deny narrative. For epic items the
    effective worktree is resolved per target from ``ctx.chain_worktrees``;
    the resulting path is recorded on the Failure so deny narratives
    show the lane the operator should be in.
    """
    if not target_path:
        return None

    effective_wt = _effective_worktree_for(target_path, cwd, ctx)

    if is_free_path_basename_redirect(
        target_path=target_path,
        cwd=cwd,
        ctx=ctx,
        effective_worktree=effective_wt,
    ):
        return None

    if outside_claim_domain(
        target_path=target_path, cwd=cwd, ctx=ctx, effective_worktree=effective_wt
    ):
        return None

    rel_root = domain_root_for_absolute_target(
        target_path=target_path,
        cwd=cwd,
        ctx=ctx,
        effective_worktree=effective_wt,
    )
    rel = _make_repo_relative(target_path, rel_root or cwd)
    in_coverage = _path_within_coverage(
        rel,
        ctx.covered_paths,
        ctx.covered_target_kinds,
    )

    if not in_coverage:
        # Worktree-less claim: widening does not unblock; narrative
        # teaches worktree_preflight instead. Both worktree_path empty
        # and no chain enumeration are required (epic + matched chain
        # falls through to OUT_OF_CLAIM as before).
        if not effective_wt and not ctx.chain_worktrees:
            return Failure(mode=WORKTREE_UNRESOLVED, target_path=target_path)
        return Failure(
            mode=OUT_OF_CLAIM,
            target_path=target_path,
            effective_worktree_path=effective_wt,
        )

    # In-coverage by relative path — verify physical worktree binding.
    if not effective_wt:
        return None  # claim is not worktree-bound; in-coverage suffices

    if os.path.isabs(target_path):
        resolved = Path(target_path).resolve()
    else:
        resolved = (Path(cwd) / target_path).resolve()

    expected_root = Path(effective_wt).resolve()
    expected_str = str(expected_root)
    resolved_parent = str(resolved.parent)

    if resolved_parent == expected_str or resolved_parent.startswith(
        expected_str + os.sep
    ):
        return None
    if str(resolved) == expected_str:
        return None

    # In-coverage but physical path lives elsewhere — wrong-cwd.
    return Failure(
        mode=WRONG_CWD,
        target_path=target_path,
        resolved_parent=resolved_parent,
        effective_worktree_path=effective_wt,
    )


# Re-export the active-claim resolver from its sibling so callers that
# already imported via this module continue to resolve.
from yoke_core.domain.path_claim_active_claim_lookup import (  # noqa: E402
    resolve_active_claim_for_session,
)


__all__ = [
    "ClaimContext",
    "Failure",
    "OUT_OF_CLAIM",
    "WORKTREE_UNRESOLVED",
    "WRONG_CWD",
    "evaluate_target",
    "resolve_active_claim_for_session",
    "widen_template",
]

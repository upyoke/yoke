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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from yoke_core.domain.path_claim_active_claim_lookup import (
    _pick_chain_for_target,
)


# Failure mode constants — both guards reference these.
OUT_OF_CLAIM = "out-of-claim"
WRONG_CWD = "wrong-cwd"
# Claim has no worktree binding (``items.worktree`` empty). Narrative
# teaches ``worktree_preflight``, NOT the ``path-claims widen`` template.
WORKTREE_UNRESOLVED = "worktree-unresolved"


@dataclass(frozen=True)
class ClaimContext:
    """Readable view of an active path claim used by guards.

    ``covered_paths`` is the list of repo-relative path strings the
    claim covers (resolved from ``path_claim_targets`` via
    ``path_targets.path_string``). For issue items ``worktree_path`` is
    the absolute worktree root the claim was issued for. For epic items
    ``worktree_path`` is ``None`` and ``chain_worktrees`` carries the
    ``((branch, absolute_path), ...)`` enumeration; the effective
    worktree is then chosen per-evaluation by matching the inbound
    target path against each chain root, so path-driven checks can map
    an inbound file to the lane-local claim that actually covers it.
    """

    claim_id: int
    item_id: Optional[int]
    integration_target: str
    state: str
    covered_paths: Tuple[str, ...]
    worktree_path: Optional[str]
    project_repo_path: Optional[str] = None
    project: str = "yoke"
    item_type: str = ""
    chain_worktrees: Tuple[Tuple[str, str], ...] = ()

    @classmethod
    def from_claim(cls, claim: Dict[str, Any]) -> "ClaimContext":
        """Build a :class:`ClaimContext` from a ``get_claim``-shaped dict.

        Tolerates injection-friendly callers that pass extra keys like
        ``covered_paths`` and ``worktree_path`` directly (used by tests
        that don't build a full DB fixture).
        """
        covered = tuple(claim.get("covered_paths") or ())
        raw_chains = claim.get("chain_worktrees") or ()
        chains: Tuple[Tuple[str, str], ...] = tuple(
            (str(b), str(p)) for b, p in raw_chains
        )
        return cls(
            claim_id=int(claim.get("id") or claim.get("claim_id") or 0),
            item_id=_coerce_int(claim.get("item_id")),
            integration_target=str(claim.get("integration_target") or ""),
            state=str(claim.get("state") or ""),
            covered_paths=covered,
            worktree_path=claim.get("worktree_path"),
            project_repo_path=claim.get("project_repo_path"),
            project=str(claim.get("project") or "yoke"),
            item_type=str(claim.get("item_type") or ""),
            chain_worktrees=chains,
        )


@dataclass(frozen=True)
class Failure:
    """One target's failure reason, consumed by the guard's narrative.

    ``effective_worktree_path`` is the worktree root used for the
    decision. For issue items this equals ``ctx.worktree_path``. For
    epic items it is the chain worktree path that matched the
    inbound target path; narratives prefer this over ``ctx.worktree_path``
    so the operator sees the correct lane in the deny output.
    """

    mode: str  # OUT_OF_CLAIM | WRONG_CWD
    target_path: str
    resolved_parent: str = ""
    effective_worktree_path: str = ""


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def widen_template(
    *, claim_id: Optional[int], item_id: Optional[int], target_path: str,
) -> str:
    """Return the canonical ``yoke claims path widen`` remediation.

    The template includes the offending path so the operator's next
    action is one mechanical paste.
    """
    cid = claim_id if claim_id is not None else "<claim_id>"
    item = f"YOK-{item_id}" if item_id is not None else "YOK-N"
    return (
        "yoke claims path widen "
        f"--claim-id {cid} --add-paths {target_path} "
        f"--reason \"cover target path\" --item {item}"
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


def _path_is_under(path: Path, root: str) -> bool:
    if not root:
        return False
    try:
        resolved_root = Path(root).expanduser().resolve()
        path.relative_to(resolved_root)
        return True
    except (OSError, ValueError):
        return False


def _effective_worktree_for(target_path: str, cwd: str, ctx: ClaimContext) -> str:
    """Return the worktree root that binds ``target_path`` under ``ctx``.

    For issue items this is ``ctx.worktree_path`` (or empty when none).
    For epic items the worktree is chosen by matching ``target_path``
    against ``ctx.chain_worktrees`` — the chain whose absolute path is
    an ancestor of the target wins. Returns ``""`` when nothing matches
    (caller falls through to ``project_repo_path``).
    """
    if ctx.item_type == "epic" and ctx.chain_worktrees:
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


def _domain_root_for_absolute_target(
    *,
    target_path: str,
    cwd: str,
    ctx: ClaimContext,
    effective_worktree: str = "",
) -> Optional[str]:
    if not os.path.isabs(target_path):
        return None
    try:
        resolved = Path(target_path).expanduser().resolve()
    except OSError:
        return None
    wt_root = effective_worktree or ctx.worktree_path
    for root in (wt_root, ctx.project_repo_path):
        if root and _path_is_under(resolved, root):
            return root
    if cwd and _path_is_under(resolved, cwd):
        return cwd
    return None


def _outside_claim_domain(
    *,
    target_path: str,
    cwd: str,
    ctx: ClaimContext,
    effective_worktree: str = "",
) -> bool:
    if not os.path.isabs(target_path):
        return False
    if _domain_root_for_absolute_target(
        target_path=target_path,
        cwd=cwd,
        ctx=ctx,
        effective_worktree=effective_worktree,
    ):
        return False
    return True


def _path_within_coverage(rel_path: str, covered: Tuple[str, ...]) -> bool:
    """Return True when ``rel_path`` is inside any covered root.

    Coverage roots may be files (exact match) or directories (prefix
    match with a trailing ``/`` boundary so ``runtime/api`` does not
    match ``runtime/api2`` accidentally).
    """
    norm = rel_path.replace(os.sep, "/").lstrip("/")
    for root in covered:
        croot = (root or "").strip().replace(os.sep, "/").lstrip("/")
        if not croot:
            continue
        if norm == croot:
            return True
        if norm.startswith(croot.rstrip("/") + "/"):
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

    if _outside_claim_domain(
        target_path=target_path, cwd=cwd, ctx=ctx, effective_worktree=effective_wt
    ):
        return None

    rel_root = _domain_root_for_absolute_target(
        target_path=target_path,
        cwd=cwd,
        ctx=ctx,
        effective_worktree=effective_wt,
    )
    rel = _make_repo_relative(target_path, rel_root or cwd)
    in_coverage = _path_within_coverage(rel, ctx.covered_paths)

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

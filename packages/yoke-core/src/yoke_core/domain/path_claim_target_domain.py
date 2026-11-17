"""Claim-domain membership helpers for path-claim target resolution."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from yoke_contracts.hook_runner.bash_paths import (
    canonical_native_path,
    is_absolute,
    windows_path,
)
from typing import Optional, Tuple

from yoke_core.domain.path_claim_target_context import ClaimContext


def claim_domain_roots(
    ctx: ClaimContext,
    effective_worktree: str = "",
) -> Tuple[str, ...]:
    """Return worktree / project roots that define the claim domain."""
    roots: list[str] = []
    for root in (effective_worktree or ctx.worktree_path, ctx.project_repo_path):
        if isinstance(root, str) and root.strip():
            roots.append(root)
    return tuple(roots)


def path_is_under(path: Path, root: str) -> bool:
    if not root:
        return False
    try:
        text, root_text = canonical_native_path(str(path)), canonical_native_path(root)
        if windows_path(text) or windows_path(root_text):
            text, root_text = (
                text.replace("\\", "/").casefold(),
                root_text.replace("\\", "/").casefold(),
            )
        PurePosixPath(text).relative_to(PurePosixPath(root_text))
        return True
    except (OSError, ValueError):
        return False


def cwd_in_claim_domain(
    cwd: str,
    ctx: ClaimContext,
    effective_worktree: str = "",
) -> bool:
    """True when ``cwd`` itself sits inside the claim's worktree or project."""
    if not cwd:
        return False
    try:
        resolved_cwd = canonical_native_path(cwd)
    except OSError:
        return False
    for root in claim_domain_roots(ctx, effective_worktree):
        if path_is_under(resolved_cwd, root):
            return True
    return False


def is_basename_target(target_path: str) -> bool:
    """True for a single path segment (``spec.md``), not a repo-relative tree."""
    cleaned = (target_path or "").strip()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not cleaned or cleaned in {".", ".."}:
        return False
    norm = cleaned.replace("\\", "/")
    if norm.startswith("../") or "/../" in f"/{norm}/":
        return False
    return "/" not in norm


def domain_root_for_absolute_target(
    *,
    target_path: str,
    cwd: str,
    ctx: ClaimContext,
    effective_worktree: str = "",
) -> Optional[str]:
    if not is_absolute(target_path):
        return None
    try:
        resolved = canonical_native_path(target_path)
    except OSError:
        return None
    for root in claim_domain_roots(ctx, effective_worktree):
        if path_is_under(resolved, root):
            return root
    # Cwd is only a domain root when it is itself inside the claim domain.
    # A free-path scratchpad cwd must not pull absolute scratch writes into
    # coverage checking.
    if (
        cwd
        and path_is_under(resolved, cwd)
        and cwd_in_claim_domain(cwd, ctx, effective_worktree)
    ):
        return cwd
    return None


def outside_claim_domain(
    *,
    target_path: str,
    cwd: str,
    ctx: ClaimContext,
    effective_worktree: str = "",
) -> bool:
    if not is_absolute(target_path):
        return False
    if domain_root_for_absolute_target(
        target_path=target_path,
        cwd=cwd,
        ctx=ctx,
        effective_worktree=effective_worktree,
    ):
        return False
    return True


def is_free_path_basename_redirect(
    *,
    target_path: str,
    cwd: str,
    ctx: ClaimContext,
    effective_worktree: str = "",
) -> bool:
    """True for ``> spec.md`` from a cwd outside the claim domain.

    Repo-shaped relatives (``runtime/api/foo.py``) stay claim-gated even
    when the harness cwd is a free-path directory; only basename scratch
    redirects are treated as session-temp writes.
    """
    if is_absolute(target_path) or not is_basename_target(target_path):
        return False
    if not cwd or cwd_in_claim_domain(cwd, ctx, effective_worktree):
        return False
    return True


__all__ = [
    "claim_domain_roots",
    "cwd_in_claim_domain",
    "domain_root_for_absolute_target",
    "is_basename_target",
    "is_free_path_basename_redirect",
    "outside_claim_domain",
    "path_is_under",
]

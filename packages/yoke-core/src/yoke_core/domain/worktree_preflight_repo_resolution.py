"""Item-project repo-root resolution shared by the surfaces that act on it.

A work item's implementation lane belongs in the checkout of the ITEM's
project, not the checkout the session happens to be standing in. Deriving
the lane repo from the harness cwd created wrong-repo lanes for cross-repo
items: an item prepared from another project's session landed its worktree
in that session's checkout, registered it as the item lane, and every later
surface inherited the wrong authority. The worktree preflight resolves the
lane repo here, and the standalone merge boundary resolves the same repo the
same way, so a lane always merges where it was prepared.

Resolution order:

1. An explicit ``repo_root`` override wins untouched (operator/test seam).
2. An explicit ``--project`` flag must AGREE with the item's own project
   when both are known — a mismatch is a refusal, not a silent preference.
3. The item's project slug resolves through the machine-config checkout
   mapping (``checkout_for_project_slug``). A mapped project uses its
   mapping even when the session stands in a different repo.
4. An UNMAPPED project refuses with the registration recipe instead of
   falling back to the session's repo — the fallback is exactly how the
   wrong-repo lane was minted.
5. Only when the item's project is unknown (degraded detail read) does the
   legacy cwd derivation apply, preserving offline behavior.
"""

from __future__ import annotations

from typing import Mapping, Optional, Tuple


def resolve_preflight_repo_root(
    *,
    item: Mapping,
    project_flag: Optional[str],
    repo_root_override: Optional[str],
) -> Tuple[str, str]:
    """Return ``(repo_root, error)`` — exactly one side is non-empty.

    ``item`` is the ``items.detail.get`` item mapping (may be empty when
    the read degraded). ``error`` carries a rendered refusal narrative
    naming the repair recipe; the caller blocks on it verbatim.
    """
    if repo_root_override:
        return str(repo_root_override), ""

    item_slug = str((item.get("project") or {}).get("slug") or "").strip()
    flag_slug = str(project_flag or "").strip()

    if flag_slug and item_slug and flag_slug != item_slug:
        return "", (
            f"--project {flag_slug!r} disagrees with the item's project "
            f"{item_slug!r}. The lane belongs in the item's project "
            "checkout; drop the flag or pass the matching slug."
        )

    slug = item_slug or flag_slug
    if not slug:
        return _cwd_fallback()

    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_slug,
    )

    checkout = checkout_for_project_slug(slug)
    if checkout is not None:
        return str(checkout), ""
    if item_slug:
        return "", (
            f"project {item_slug!r} has no machine-local checkout mapping, "
            "and falling back to the session's own repo would act on the "
            "wrong repository. Register the mapping first:\n"
            f"    yoke project register <checkout-path> --project-id <id>\n"
            "then re-run this operation."
        )
    return _cwd_fallback()


def _cwd_fallback() -> Tuple[str, str]:
    from yoke_core.domain.worktree_paths import _resolve_repo_root_from_cwd

    root = _resolve_repo_root_from_cwd()
    if root:
        return str(root), ""
    return "", "Could not resolve repo root for preflight."


__all__ = ["resolve_preflight_repo_root"]

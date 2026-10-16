"""Advance a project's default-branch checkout after a landing.

Session start does the same through
:func:`yoke_harness.hooks.session_lifecycle.sync_session_main_checkout`, on
the machine that owns the checkout. Both ask the same question the preparation surfaces ask — is this
checkout's default branch current with its remote, and can it be brought
current without touching anything local — so both delegate to the one
implementation in :mod:`yoke_cli.config.repo_upstream_freshness` rather
than carrying a second one. A landed merge is never unwound by local state:
local commits and uncommitted changes are preserved, and whatever stopped
the update comes back as an advisory naming its own recovery.
"""

from __future__ import annotations

from yoke_cli.config.repo_upstream_freshness import refresh_base_branch

NOT_SYNCED = "main checkout not fast-forwarded"


def fast_forward_main_checkout(repo_root: str, target: str) -> str:
    """Bring ``target`` current with its remote; return an advisory.

    Empty when there was nothing to report: the branch was already current,
    or it fast-forwarded cleanly. A landing calls this after publishing, so
    the advisory is a warning on an otherwise successful merge, never a
    failure of it.
    """
    if not repo_root:
        return f"{NOT_SYNCED}: checkout root is missing"
    freshness = refresh_base_branch(repo_root, target, use_cache=False)
    if not freshness.needs_attention:
        return ""
    return f"{NOT_SYNCED}: {freshness.note}"


__all__ = [
    "NOT_SYNCED",
    "fast_forward_main_checkout",
]

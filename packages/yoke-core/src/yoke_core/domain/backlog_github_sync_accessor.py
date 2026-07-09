"""Lazy accessor for ``backlog_github_sync``.

Each sibling sync module (``backlog_github_label_sync``,
``backlog_github_item_create``, ``backlog_github_state_sync``, etc.)
needs to call into the canonical ``backlog_github_sync`` shim for
``_dry_run``, ``_github_auth_available``, ``_validate_issue_in_repo``,
and the high-level helpers re-exported there. A module-level
``from yoke_core.domain import backlog_github_sync`` re-entered the
sibling under ``-m`` execution because the entrypoint runs the shim
under ``__main__`` and the re-import would try to load it again under
its proper name while the sibling itself is mid-load.

This module hosts the lazy accessor used by every sibling so the
docstring + import + return triple lives in exactly one place. Tests
patching ``yoke_core.domain.backlog_github_sync.<symbol>`` still take
effect because :func:`bgs` returns the live module reference.
"""

from __future__ import annotations


def bgs():
    """Return the live ``backlog_github_sync`` module reference."""
    from yoke_core.domain import backlog_github_sync as bgs_mod
    return bgs_mod


__all__ = ["bgs"]

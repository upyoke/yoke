"""Decide whether preparation may start from this checkout's default branch.

The freshness reading itself belongs to
:mod:`yoke_core.domain.repo_upstream_freshness`; what that reading means
for preparation belongs here, because the two branches of preparation ask
different questions of it.

A lane needs a revision it can be cut from that holds everything the
remote has. The fetched upstream is that revision even when the local
branch could not be moved, so a branch merely behind still yields a
current lane. A diverged branch does not: its lane would have to start
from local, which is missing the commits just fetched, so it refuses
pending reconciliation rather than quietly producing stale work. Laneless
work has no lane at all — it commits onto the default branch itself — so
it needs that branch to hold everything the remote has. Neither may
proceed when the remote could not be read at all, because "prepare from
whatever is on disk" is the silent stale start the whole step exists to
prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_core.domain.repo_upstream_freshness import (
    UpstreamFreshness,
    refresh_base_branch,
)
from yoke_core.domain.worktree_preflight_steps import (
    BLOCK_UPSTREAM_STALE,
    BLOCK_UPSTREAM_UNVERIFIED,
)


@dataclass(frozen=True)
class UpstreamGate:
    """The reading, plus the refusal it implies for this preparation."""

    freshness: Optional[UpstreamFreshness] = None
    block_kind: str = ""
    narrative: str = ""


def gate_upstream_for_preparation(
    repo_root: str,
    item: Mapping[str, Any],
    *,
    no_worktree: bool,
) -> UpstreamGate:
    """Read the remote and say whether this preparation may proceed.

    The branch read is the one the item's project declares, and only that
    one. An item with no project — the folder-project floor case — resolves
    no default branch, and whatever checkout the caller happens to be
    standing in is not a substitute for one: gating on it would refuse work
    over the freshness of a repository the item has nothing to do with. No
    checkout or no declared branch therefore yields an empty gate.
    """
    declared = str((item.get("project") or {}).get("default_branch") or "")
    if not repo_root or not declared:
        return UpstreamGate()
    freshness = refresh_base_branch(repo_root, declared)
    if not freshness.verified:
        return UpstreamGate(freshness, BLOCK_UPSTREAM_UNVERIFIED, freshness.note)
    stale = (
        not freshness.local_branch_current
        if no_worktree
        else not freshness.lane_base_is_current
    )
    if stale:
        return UpstreamGate(freshness, BLOCK_UPSTREAM_STALE, freshness.note)
    return UpstreamGate(freshness)


__all__ = ["UpstreamGate", "gate_upstream_for_preparation"]

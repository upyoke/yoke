"""Lane membership for the lane-main-write guard.

One session may hold several lanes of one item at once — a Blitz
registers worker lanes beside its integration lane, and an epic's task
lanes are recorded under the epic — so "the held lane" is a set. The
guard asks two questions about every write target, in this order:

* Is it inside a lane this session holds? Then it is a lane write and
  this guard has nothing to say, whichever held lane it lands in.
* Otherwise, which held claim answers for it? A target in the main
  checkout is answered by a claim whose lane lives under that checkout.
  A target under ``.worktrees`` that belongs to no held lane is a lane
  escape — a write into somebody else's lane — and is refused the same
  way, with a held lane offered instead.

The "use instead" path is the target's repo-relative path inside the
held lane. A lane-escape target is made relative to the foreign lane,
not to the checkout root, so the suggestion never nests one lane's
``.worktrees`` inside another.
"""

from __future__ import annotations

from pathlib import PureWindowsPath, PurePosixPath
from yoke_contracts.machine_config.checkout import LANES_DIR
from yoke_contracts.hook_runner.bash_paths import lexical_client_path, join_path, windows_path
from typing import Optional, Sequence

from yoke_core.domain.lint_session_cwd_path_authority import (
    is_inside,
    is_inside_control_plane,
    repo_root_from_worktree_path,
)
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree



def held_lane_for(
    target: str,
    claims: Sequence[ClaimedWorktree],
) -> Optional[ClaimedWorktree]:
    """The held claim whose lane contains *target*, if any."""
    for claim in claims:
        if is_inside(target, claim.worktree_path):
            return claim
    return None


def _under_worktrees(target: str, repo_root: str) -> bool:
    return is_inside(target, join_path(repo_root, LANES_DIR))


def is_lane_escape(
    target: str,
    claims: Sequence[ClaimedWorktree],
    repo_root: str,
) -> bool:
    """True when *target* is under ``.worktrees`` but inside no held lane."""
    if held_lane_for(target, claims) is not None:
        return False
    return _under_worktrees(target, repo_root)


def matching_claim_for_main_target(
    target: str,
    claims: Sequence[ClaimedWorktree],
    repo_roots: Sequence[str],
) -> Optional[ClaimedWorktree]:
    """The held claim that answers for a refusable *target*, else ``None``."""
    if held_lane_for(target, claims) is not None:
        return None
    for claim in claims:
        root = repo_root_from_worktree_path(claim.worktree_path)
        if root and (
            is_inside_control_plane(target, root)
            or is_lane_escape(target, claims, root)
        ):
            return claim
    for root in repo_roots:
        if is_inside_control_plane(target, root):
            for claim in claims:
                if repo_root_from_worktree_path(claim.worktree_path) == root:
                    return claim
            if claims:
                return claims[0]
    return None


def lane_equivalent_path(main_target: str, claim: ClaimedWorktree) -> str:
    """Suggest a source destination using client paths, without probing server disk."""
    root = repo_root_from_worktree_path(claim.worktree_path)
    if not root:
        return claim.worktree_path
    path_type = PureWindowsPath if windows_path(main_target) or windows_path(root) else PurePosixPath
    try:
        rel = path_type(lexical_client_path(main_target)).relative_to(
            path_type(lexical_client_path(root))
        )
    except (OSError, ValueError):
        return claim.worktree_path
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == LANES_DIR:
        # A foreign lane's file: keep only its lane-relative path.
        rel = path_type(*parts[2:]) if len(parts) > 2 else path_type(".")
    if ".git" in rel.parts:
        # No source equivalent: linked worktrees have a .git file. Without
        # client proof the write still refuses, but cannot be redirected there.
        return ""
    return join_path(claim.worktree_path, str(rel).replace("\\", "/"))


__all__ = [
    "held_lane_for",
    "is_lane_escape",
    "lane_equivalent_path",
    "matching_claim_for_main_target",
]

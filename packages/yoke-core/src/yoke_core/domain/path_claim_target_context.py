"""Data views shared by path-claim target guards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class ClaimContext:
    """Readable view of an active path claim used by guards.

    ``covered_paths`` contains repo-relative paths resolved from claim
    targets. Single-lane claims carry one ``worktree_path``; task-lane
    claims enumerate ``chain_worktrees`` for per-target lane selection.
    """

    claim_id: int
    item_id: Optional[int]
    integration_target: str
    state: str
    covered_paths: Tuple[str, ...]
    worktree_path: Optional[str]
    covered_target_kinds: Tuple[Tuple[str, str], ...] = ()
    project_repo_path: Optional[str] = None
    project: str = "yoke"
    item_ref: Optional[str] = None
    task_lanes: bool = False
    chain_worktrees: Tuple[Tuple[str, str], ...] = ()

    @classmethod
    def from_claim(cls, claim: Dict[str, Any]) -> "ClaimContext":
        """Build a context from a ``get_claim``-shaped dictionary."""
        covered = tuple(claim.get("covered_paths") or ())
        raw_targets = claim.get("covered_target_kinds") or ()
        target_kinds: Tuple[Tuple[str, str], ...] = tuple(
            (str(path), str(kind)) for path, kind in raw_targets
        )
        raw_chains = claim.get("chain_worktrees") or ()
        chains: Tuple[Tuple[str, str], ...] = tuple(
            (str(branch), str(path)) for branch, path in raw_chains
        )
        return cls(
            claim_id=int(claim.get("id") or claim.get("claim_id") or 0),
            item_id=_coerce_int(claim.get("owner_item_id")),
            integration_target=str(claim.get("integration_target") or ""),
            state=str(claim.get("state") or ""),
            covered_paths=covered,
            covered_target_kinds=target_kinds,
            worktree_path=claim.get("worktree_path"),
            project_repo_path=claim.get("project_repo_path"),
            project=str(claim.get("project") or "yoke"),
            item_ref=(str(claim["item_ref"]).strip() or None)
            if claim.get("item_ref") is not None
            else None,
            task_lanes=bool(claim.get("task_lanes", False)),
            chain_worktrees=chains,
        )


@dataclass(frozen=True)
class Failure:
    """One target's failure reason, consumed by guard narratives."""

    mode: str
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


__all__ = ["ClaimContext", "Failure"]

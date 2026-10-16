"""The control-plane half of the worktree-health answer: who owns each lane.

The health check runs on the machine holding the checkout, because only that
machine can see the lanes — but the two facts it needs about each one are
control-plane facts: which item registered it, and whether anything still holds
cleanup authority over it. Both are read through registered relayed surfaces
rather than local SQL, so a project relaying over https — which has a checkout
but no local database — can still be checked.

Both reads fail toward "cannot answer" rather than toward a verdict. An
unreadable inventory is ``None``, which the check reports as N/A: a caller that
read zero lanes from an unreachable control plane would otherwise conclude the
machine has nothing to retire. An unreadable authority verdict reads as still
held, because an unprovable claim is not an absent one.

Authority verdicts for every lane the check may retire arrive in one batched
read, so a machine holding dozens of landed lanes pays one round trip rather
than one per lane against the check's budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from yoke_core.domain.control_plane_transport import relay
from yoke_core.engines.prune_authority_batch import LANE_INVALID


ACTIVE_AUTHORITY_BLOCK = "cleanup authority is active"
UNREADABLE_AUTHORITY_BLOCK = "cleanup authority is unreadable"

LaneKey = Tuple[str, str]


class LaneRow:
    """One registered lane row, as the worktree-health check consumes it."""

    __slots__ = (
        "item_id",
        "public_ref",
        "status",
        "branch",
        "path",
        "state",
        "target_branch",
    )

    def __init__(self, row: Dict[str, object]) -> None:
        self.item_id = int(row.get("item_id") or 0)
        self.public_ref = str(row.get("public_ref") or "")
        self.status = str(row.get("status") or "")
        self.branch = str(row.get("branch") or "")
        self.path = str(row.get("path") or "")
        self.state = str(row.get("state") or "")
        self.target_branch = str(row.get("target_branch") or "main")


def lane_inventory(project: str) -> List[LaneRow] | None:
    """Every registered lane for *project*, or ``None`` when unreadable."""
    try:
        result = relay("item_worktrees.inventory", {"project": str(project)})
    except Exception:  # noqa: BLE001 - unreachable authority == cannot answer
        return None
    rows = result.get("lanes")
    if not isinstance(rows, list):
        return None
    return [LaneRow(row) for row in rows if isinstance(row, dict)]


@dataclass(frozen=True)
class AuthorityBlocks:
    """Why cleanup authority forbids pruning each (branch, path) lane.

    An empty block means the lane is prunable. ``failure`` names why the
    batched read could not answer; every lane then reads as still held.
    """

    blocks: Dict[LaneKey, str]
    failure: str = ""

    def block(self, branch: str, path: str) -> str:
        return self.blocks.get((branch, path), UNREADABLE_AUTHORITY_BLOCK)


def authority_blocks(lanes: Iterable[LaneKey]) -> AuthorityBlocks:
    """Read every lane's prune verdict through one control-plane call."""
    keys = list(dict.fromkeys(lanes))
    if not keys:
        return AuthorityBlocks({})
    payload = {
        "lanes": [
            {"branch": branch, **({"path": path} if path else {})}
            for branch, path in keys
        ]
    }
    try:
        verdicts = relay("merge.prune.authority_verdicts", payload).get("verdicts")
        if not isinstance(verdicts, list) or len(verdicts) != len(keys):
            raise ValueError(
                f"answered {len(verdicts) if isinstance(verdicts, list) else 'no'} "
                f"verdicts for {len(keys)} lanes"
            )
    except Exception as exc:  # noqa: BLE001 - fail closed: unprovable == still held
        failure = str(exc) or type(exc).__name__
        return AuthorityBlocks(
            {key: UNREADABLE_AUTHORITY_BLOCK for key in keys}, failure
        )
    return AuthorityBlocks(
        {key: _verdict_block(verdict) for key, verdict in zip(keys, verdicts)}
    )


def _verdict_block(verdict: object) -> str:
    if not isinstance(verdict, dict):
        return UNREADABLE_AUTHORITY_BLOCK
    if verdict.get("prunable"):
        return ""
    reason = str(verdict.get("reason") or "")
    if reason == "active_authority":
        return ACTIVE_AUTHORITY_BLOCK
    if reason.startswith(f"{LANE_INVALID}:"):
        return reason
    return f"no unique terminal owner ({reason or 'unproven'})"


__all__ = [
    "ACTIVE_AUTHORITY_BLOCK",
    "AuthorityBlocks",
    "LaneKey",
    "LaneRow",
    "UNREADABLE_AUTHORITY_BLOCK",
    "authority_blocks",
    "lane_inventory",
]

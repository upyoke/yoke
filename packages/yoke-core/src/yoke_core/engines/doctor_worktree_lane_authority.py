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
"""

from __future__ import annotations

from typing import Dict, List

from yoke_core.domain.control_plane_transport import relay


ACTIVE_AUTHORITY_BLOCK = "cleanup authority is active or unreadable"


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


def authority_block(branch: str, path: str) -> str:
    """Why cleanup authority forbids pruning this lane; empty when idle."""
    payload: Dict[str, object] = {"branch": branch}
    if path:
        payload["path"] = path
    try:
        verdict = relay("merge.prune.authority_verdict", payload)
    except Exception:  # noqa: BLE001 - fail closed: unprovable == still held
        return ACTIVE_AUTHORITY_BLOCK
    if verdict.get("prunable"):
        return ""
    reason = str(verdict.get("reason") or "")
    if reason == "active_authority":
        return ACTIVE_AUTHORITY_BLOCK
    return f"no unique terminal owner ({reason or 'unproven'})"


__all__ = [
    "ACTIVE_AUTHORITY_BLOCK",
    "LaneRow",
    "authority_block",
    "lane_inventory",
]

"""The envelope implementation-entry preparation returns to its callers.

Kept beside the orchestrator in
:mod:`yoke_core.domain.worktree_preflight` so both stay under the
authored-file line cap. The shape is the contract every entry point reads
— the advance orchestrator, the Dash and Blitz preparation CLI, and the
operator-facing preflight command — so it lives in one place rather than
being re-described by each of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class WorktreePreflightOutcome:
    """Structured outcome. ``ok`` distinguishes envelope vs block."""

    ok: bool = True
    block_kind: str = ""
    narrative: str = ""
    item_id: int = 0
    branch: str = ""
    worktree_path: str = ""
    semantic_scope: str = "main"
    physical_cwd_mode: str = ""
    actions_taken: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_envelope(self) -> Dict[str, Any]:
        """Serialise as the operator-defined execution envelope."""
        if not self.ok:
            return {
                "ok": False,
                "block_kind": self.block_kind,
                "narrative": self.narrative,
                "item_id": self.item_id,
            }
        return {
            "ok": True,
            "item_id": self.item_id,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "semantic_scope": self.semantic_scope,
            "physical_cwd_mode": self.physical_cwd_mode,
            "actions_taken": list(self.actions_taken),
            "notes": list(self.notes),
        }


__all__ = ["WorktreePreflightOutcome"]

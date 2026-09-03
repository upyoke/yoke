"""Best-effort physical lane retirement after an item becomes terminal.

The control plane releases lane rows and claims in the status transaction.
This module owns the matching machine-local obligation: prove that each lane
is clean and merged, then remove its worktree and branch, and then run the
machine-wide merged-lane sweep so a lane an earlier landing preserved is
examined again now. Refusal is evidence, not a reason to unwind the committed
terminal transition: each preserved lane of the item's own is named on the
returned warnings and recorded as a ``LandedLanePreserved`` event, so the
refusal outlives the terminal output that first showed it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.engines.merge_landed_lane_cleanup import prune_landed_lane
from yoke_core.engines.merge_worktree_safe_prune import (
    WorktreeSweep,
    prune_managed_worktrees,
)

LANE_PRESERVED_EVENT_NAME = "LandedLanePreserved"


@dataclass(frozen=True)
class TerminalLaneCloseOut:
    """Warnings for the item's own lanes plus the machine-wide sweep result."""

    warnings: tuple[str, ...] = ()
    sweep: dict[str, Any] = field(default_factory=dict)


def _closing_session_id(session_id: str) -> str:
    return session_id or str(resolve_ambient_session_id() or "")


def _foreign_claim_reason(item: dict[str, Any], session_id: str) -> str:
    """Preserve only when another session still holds the item.

    A live claim belonging to this close-out is not a preserve: the status
    transaction releases that row, and ``item_cleanup_authority_blocks_prune``
    would otherwise treat the closer as active authority and leave the lane.
    Empty ``session_id`` falls back to ambient identity so a flag-less merge
    CLI still recognizes its own snapshot claim.
    """
    claim = item.get("claim") or {}
    holder = str(claim.get("session_id") or "")
    closer = _closing_session_id(session_id)
    if not holder or (closer and holder == closer):
        return ""
    return f"live work claim belongs to session {holder}"


def _terminal_status(item: dict[str, Any], target_status: str) -> bool:
    workflow = item.get("workflow") or {}
    terminal_ids = {str(value) for value in workflow.get("terminal_stage_ids") or ()}
    return bool(target_status and target_status in terminal_ids)


def _leave_doomed_worktree(path: Path, repo_root: Path) -> None:
    try:
        if Path.cwd().resolve().is_relative_to(path.resolve()):
            os.chdir(repo_root)
    except OSError:
        return
    from yoke_core.domain.worktree_import_reseat import reseat_loaded_packages

    reseat_loaded_packages(doomed_root=str(path), surviving_root=str(repo_root))


def _record_preserved_lane(
    item: dict[str, Any], *, branch: str, path: str, target: str, reason: str
) -> str:
    """Record the refusal as an event; return a warning when that was refused."""
    try:
        response = call_dispatcher(
            function_id="events.emit",
            target=TargetRef(kind="global"),
            payload={
                "name": LANE_PRESERVED_EVENT_NAME,
                "kind": "lifecycle",
                "type": "merge_lifecycle",
                "source_type": "system",
                "severity": "WARN",
                "outcome": "preserved",
                "project": str((item.get("project") or {}).get("slug") or ""),
                "item_id": str(int(item["id"])),
                "context": {
                    "branch": branch,
                    "path": path,
                    "target": target,
                    "reason": reason,
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 - the lane is already preserved
        detail = str(exc)
    else:
        if response.success:
            return ""
        detail = (
            response.error.message if response.error is not None else "refused"
        )
    return f"{LANE_PRESERVED_EVENT_NAME} not recorded for {branch}: {detail}"


def _cleanup_terminal_item_lanes(
    item: dict[str, Any],
    *,
    target_status: str,
    session_id: str = "",
    repo_root: str | Path | None = None,
    target_branch: str = "",
    emit: Optional[Callable[..., Any]] = None,
    prune: Callable[..., tuple[str, ...]] = prune_landed_lane,
    sweep: Callable[..., WorktreeSweep] = prune_managed_worktrees,
) -> TerminalLaneCloseOut:
    """Retire every surviving lane, then sweep lanes earlier landings kept."""
    if not _terminal_status(item, target_status):
        return TerminalLaneCloseOut()
    public_ref = str(item.get("public_ref") or item.get("id") or "item")
    project = item.get("project") or {}
    root = (
        Path(repo_root)
        if repo_root
        else checkout_for_project_id(
            int(project.get("id")) if project.get("id") is not None else None
        )
    )
    if root is None or not root.is_dir():
        return TerminalLaneCloseOut(
            (f"{public_ref}: terminal lane cleanup preserved: checkout unavailable",)
        )
    root = root.resolve()
    target = target_branch or str(project.get("default_branch") or "main")
    authority_block = _foreign_claim_reason(item, session_id)
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()

    for lane in item.get("worktrees") or ():
        branch = str(lane.get("branch") or "").strip()
        path_text = str(lane.get("path") or "").strip()
        identity = (branch, path_text)
        if not branch or identity in seen:
            continue
        seen.add(identity)
        lane_path = Path(path_text).resolve() if path_text else None
        if not git.branch_exists(str(root), branch) and not (
            lane_path is not None and lane_path.exists()
        ):
            continue
        if not authority_block and lane_path is not None:
            _leave_doomed_worktree(lane_path, root)
        preserved = prune(
            repo_root=str(root),
            branch=branch,
            target=target,
            item_id=int(item["id"]),
            emit=emit,
            authority_block=authority_block,
        )
        location = f" at {path_text}" if path_text else " (branch only)"
        for reason in preserved:
            warnings.append(f"{public_ref}{location}: {reason}")
            refused = _record_preserved_lane(
                item, branch=branch, path=path_text, target=target, reason=reason
            )
            if refused:
                warnings.append(refused)

    swept = sweep(repo_root=str(root), target=target, emit=emit)
    return TerminalLaneCloseOut(tuple(warnings), swept.payload())


def cleanup_terminal_item_lanes(
    item: dict[str, Any],
    *,
    target_status: str,
    session_id: str = "",
    repo_root: str | Path | None = None,
    target_branch: str = "",
    emit: Optional[Callable[..., Any]] = None,
    prune: Callable[..., tuple[str, ...]] = prune_landed_lane,
    sweep: Callable[..., WorktreeSweep] = prune_managed_worktrees,
) -> TerminalLaneCloseOut:
    """Retire terminal lanes without unwinding the committed transition."""
    try:
        return _cleanup_terminal_item_lanes(
            item,
            target_status=target_status,
            session_id=session_id,
            repo_root=repo_root,
            target_branch=target_branch,
            emit=emit,
            prune=prune,
            sweep=sweep,
        )
    except Exception as exc:  # noqa: BLE001 - terminal state is already committed
        public_ref = str(item.get("public_ref") or item.get("id") or "item")
        return TerminalLaneCloseOut(
            (
                f"{public_ref}: terminal lane cleanup preserved after an "
                f"unexpected refusal: {exc}",
            )
        )


__all__ = [
    "LANE_PRESERVED_EVENT_NAME",
    "TerminalLaneCloseOut",
    "cleanup_terminal_item_lanes",
]

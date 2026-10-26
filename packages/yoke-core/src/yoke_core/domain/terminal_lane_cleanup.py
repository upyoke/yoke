"""Best-effort physical lane retirement after an item becomes terminal.

The control plane releases lane rows and claims in the status transaction.
This module owns the matching machine-local obligation: prove that each lane
is clean and merged, then remove its worktree and branch. A standalone
close-out then runs the machine-wide sweep, because a machine with no prod
relay — a local-only install, or one that never installed a relay — has no
other sweep; elsewhere the relay's periodic sweep covers what this one
misses. Refusal is evidence, not a reason to unwind the committed
terminal transition: each preserved lane of the item's own is named on the
returned warnings and recorded as a ``LandedLanePreserved`` event, so the
refusal outlives the terminal output that first showed it.

A cancelled item skips those proofs. Cancelling discards the work, so each
lane's worktree, local branch and remote branch are deleted outright by
``cancelled_lane_discard``, and what they held is written to the item's
Progress Log in one record.

The two phases report separately. A warning naming the closing item is about
that item's own lane; one naming the machine-wide sweep is about lanes other
items own, which the closing item never resolved a path for.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.engines.cancelled_lane_discard import (
    CANCELLED_STATUS,
    DiscardedLane,
    discard_cancelled_lane,
    record_discarded_lanes,
)
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
                "public_ref": item["public_ref"],
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
        detail = response.error.message if response.error is not None else "refused"
    return f"{LANE_PRESERVED_EVENT_NAME} not recorded for {branch}: {detail}"


def item_lane_checkout(
    item: dict[str, Any],
    *,
    repo_root: str | Path | None = None,
    target_branch: str = "",
) -> tuple[Path, str] | None:
    """Checkout and target branch for *item* when the checkout exists."""
    project = item.get("project") or {}
    project_id = int(project["id"]) if project.get("id") is not None else None
    root = Path(repo_root) if repo_root else checkout_for_project_id(project_id)
    if root is None or not root.is_dir():
        return None
    target = target_branch or str(project.get("default_branch") or "main")
    return root.resolve(), target


def sweep_managed_lanes(
    *,
    repo_root: str | Path,
    target: str,
    emit: Optional[Callable[..., Any]] = None,
    sweep: Callable[..., WorktreeSweep] = prune_managed_worktrees,
    owner: str = "",
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Run the machine-wide sweep once. A refusal is a warning, not a raise."""
    try:
        swept = sweep(repo_root=str(repo_root), target=target, emit=emit)
    except Exception as exc:  # noqa: BLE001 - the caller's own lanes are done
        whose = f"{owner}'s own lanes" if owner else "Member lanes"
        warning = (
            "machine-wide merged-lane sweep stopped after an unexpected "
            f"refusal: {exc}. {whose} were handled above; "
            "the relay's next lane sweep runs it again."
        )
        return (warning,), {}
    return (), swept.payload()


def _cleanup_terminal_item_lanes(
    item: dict[str, Any],
    *,
    target_status: str,
    session_id: str = "",
    repo_root: str | Path | None = None,
    target_branch: str = "",
    emit: Optional[Callable[..., Any]] = None,
    landing_recorded: bool = False,
    prune: Callable[..., tuple[str, ...]] = prune_landed_lane,
    discard: Callable[..., DiscardedLane] = discard_cancelled_lane,
    sweep: Callable[..., WorktreeSweep] = prune_managed_worktrees,
) -> TerminalLaneCloseOut:
    """Retire every surviving lane, then sweep lanes earlier landings kept.

    ``landing_recorded`` admits the one case a terminal status cannot cover:
    a close-out whose merge landed and whose evidence is written, but whose
    terminal transition refused. Lane release is otherwise reachable only
    from the review stage, so such an item sits at its release wait holding a
    lane nothing can retire — and every later terminal refusal on a
    delivery-bearing workflow reproduces that deadlock.

    It widens nothing about safety. Each lane still has to prove itself clean
    and merged to :func:`prune_landed_lane` before anything is removed, so a
    lane still carrying work is preserved here exactly as it always was.
    """
    if not _terminal_status(item, target_status) and not landing_recorded:
        return TerminalLaneCloseOut()
    public_ref = str(item.get("public_ref") or "<public-ref-unavailable>")
    resolved = item_lane_checkout(
        item, repo_root=repo_root, target_branch=target_branch
    )
    if resolved is None:
        return TerminalLaneCloseOut(
            (f"{public_ref}: terminal lane cleanup preserved: checkout unavailable",)
        )
    root, target = resolved
    authority_block = _foreign_claim_reason(item, session_id)
    cancelled = target_status == CANCELLED_STATUS
    warnings: list[str] = []
    discarded: list[DiscardedLane] = []
    seen: set[tuple[str, str]] = set()

    for lane in item.get("worktrees") or ():
        branch = str(lane.get("branch") or "").strip()
        path_text = str(lane.get("path") or "").strip()
        identity = (branch, path_text)
        if not branch or identity in seen:
            continue
        seen.add(identity)
        lane_path = Path(path_text).resolve() if path_text else None
        location = f" at {path_text}" if path_text else " (branch only)"
        if cancelled and authority_block:
            warnings.append(f"{public_ref}{location}: lane kept: {authority_block}")
            continue
        if (
            not cancelled
            and not git.branch_exists(str(root), branch)
            and not (lane_path is not None and lane_path.exists())
        ):
            continue
        if not authority_block and lane_path is not None:
            _leave_doomed_worktree(lane_path, root)
        if cancelled:
            lane_result = discard(
                repo_root=str(root), branch=branch, target=target, emit=emit
            )
            if lane_result != DiscardedLane(branch):
                discarded.append(lane_result)
            warnings.extend(
                f"{public_ref}{location}: {why}" for why in lane_result.kept
            )
            continue
        preserved = prune(
            repo_root=str(root),
            branch=branch,
            target=target,
            item_id=item["public_ref"],
            emit=emit,
            authority_block=authority_block,
        )
        for reason in preserved:
            warnings.append(f"{public_ref}{location}: {reason}")
            refused = _record_preserved_lane(
                item, branch=branch, path=path_text, target=target, reason=reason
            )
            if refused:
                warnings.append(refused)

    if refused := record_discarded_lanes(public_ref, tuple(discarded)):
        warnings.append(refused)

    sweep_warnings, sweep_payload = sweep_managed_lanes(
        repo_root=root, target=target, emit=emit, sweep=sweep, owner=public_ref
    )
    warnings.extend(sweep_warnings)
    return TerminalLaneCloseOut(tuple(warnings), sweep_payload)


def cleanup_terminal_item_lanes(
    item: dict[str, Any],
    *,
    target_status: str,
    session_id: str = "",
    repo_root: str | Path | None = None,
    target_branch: str = "",
    emit: Optional[Callable[..., Any]] = None,
    landing_recorded: bool = False,
    prune: Callable[..., tuple[str, ...]] = prune_landed_lane,
    discard: Callable[..., DiscardedLane] = discard_cancelled_lane,
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
            landing_recorded=landing_recorded,
            prune=prune,
            discard=discard,
            sweep=sweep,
        )
    except Exception as exc:  # noqa: BLE001 - terminal state is already committed
        public_ref = str(item.get("public_ref") or "<public-ref-unavailable>")
        return TerminalLaneCloseOut(
            (
                f"{public_ref}: terminal lane cleanup preserved after an "
                f"unexpected refusal: {exc}",
            )
        )


def record_terminal_lane_close_out(
    item: dict[str, Any],
    envelope: dict[str, Any],
    *,
    target_status: str,
    session_id: str = "",
    repo_root: str | Path | None = None,
    target_branch: str = "",
    landing_recorded: bool = False,
) -> None:
    """Retire the item's lanes and report the outcome on a result envelope.

    Every way a standalone merge reports a terminal item — the close-out it
    just ran, and the two re-entries that find the landing already recorded —
    owes the same physical retirement, so they share this one call rather
    than each deciding whether cleanup is theirs to run.
    """
    close = cleanup_terminal_item_lanes(
        item,
        target_status=target_status,
        session_id=session_id,
        repo_root=repo_root,
        target_branch=target_branch,
        landing_recorded=landing_recorded,
        emit=lambda message, **_kw: print(message, file=sys.stderr, flush=True),
    )
    envelope.setdefault("warnings", []).extend(close.warnings)
    envelope["lane_sweep"] = close.sweep


__all__ = [
    "LANE_PRESERVED_EVENT_NAME",
    "TerminalLaneCloseOut",
    "cleanup_terminal_item_lanes",
    "item_lane_checkout",
    "record_terminal_lane_close_out",
    "sweep_managed_lanes",
]

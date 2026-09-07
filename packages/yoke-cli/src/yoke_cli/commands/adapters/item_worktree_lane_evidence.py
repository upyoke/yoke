"""Decide whether an item's worktree lane can be retired without losing work.

Releasing a lane row is bookkeeping, but it authorizes discarding a directory,
so it is gated on evidence that the lane holds nothing anyone still wants.
There are exactly two ways to earn that evidence:

1. **The directory is there and clean.** Git confirms the checkout sits on the
   branch the row records and reports no modified or untracked files.
   Ignored residue that worktree prepare itself created is not dirt.

2. **The directory is already gone and the branch landed.** A merge removes a
   lane directory only after proving the branch is contained by the target,
   and it records a completed merge receipt on the item when it does. A
   missing directory with such a receipt held nothing at removal time.

The second case is deliberately narrow. A missing directory is *not* clean on
its own — an interrupted operation, a hand-deleted lane, and a wrong path in
the row all look identical from a stat call, and treating any of them as
trivially releasable would let this path discard uncommitted work the
cleanliness check exists to protect. The completed merge receipt is what
separates "this lane was retired on purpose" from "this lane is unaccounted
for".

This lives client-side because both signals are local: git can only answer
about a checkout on this machine, and a control plane reached over https holds
no checkout at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

#: How the release earned its authority, recorded on the attestation so a
#: reader can tell a git-verified clean tree from a landed-and-removed lane.
EVIDENCE_WORKTREE_CLEAN = "worktree_clean"
EVIDENCE_MERGED_AND_REMOVED = "merged_and_removed"

#: The item-owned merge receipt read. The merge boundary writes the entry
#: before the engine runs and again once the merge identity is known.
_MERGE_RECEIPT_FUNCTION = "merge_receipt.get"


def _git(args: list[str], cwd: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", cwd, *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _landed_merge_sha(target: Any, branch: str, session_id: Any) -> str:
    """The merge sha the item's receipt records for ``branch``, if any.

    Only the completed receipt carries ``merge_sha``: the merge boundary
    writes it after the engine has verified the branch reached the target, so
    its presence is the durable "this branch landed" fact that survives the
    branch ref and the lane directory both being gone. The lane row names the
    branch but not the target it landed on, so the query matches on branch.
    """
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

    try:
        response = call_dispatcher(
            function_id=_MERGE_RECEIPT_FUNCTION,
            target=target,
            payload={"branch": branch},
            actor=build_actor(session_id=session_id),
        )
    except Exception:  # noqa: BLE001 - an unreadable store is "no receipt"
        return ""
    if not response.success:
        return ""
    entry = (response.result or {}).get("entry")
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("merge_sha") or "").strip()


def attest_releasable_lane(
    worktree: Any,
    *,
    target: Any = None,
    session_id: Any = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Evidence that this lane can be retired, or the reason it cannot."""
    if not isinstance(worktree, dict):
        return None, None
    worktree_id = worktree.get("id")
    branch = worktree.get("branch")
    raw_path = worktree.get("path")
    if (
        not isinstance(worktree_id, int)
        or not isinstance(branch, str)
        or not branch
        or not isinstance(raw_path, str)
        or not raw_path
    ):
        return None, "the active lane has incomplete id, branch, or path metadata"
    path = Path(raw_path)
    if not path.is_absolute():
        return None, f"the registered lane path is not absolute: {raw_path}"

    def _attestation(evidence: str) -> dict:
        return {
            "worktree_id": worktree_id,
            "branch": branch,
            "path": raw_path,
            "observed_clean": True,
            "evidence": evidence,
        }

    if not path.is_dir():
        if _landed_merge_sha(target, branch, session_id):
            return _attestation(EVIDENCE_MERGED_AND_REMOVED), None
        return None, (
            f"the lane directory {raw_path} is gone and no completed merge "
            f"receipt records {branch!r} landing, so its contents are "
            "unaccounted for"
        )

    actual_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], raw_path)
    if actual_branch is None:
        return None, f"git could not verify the registered lane path: {raw_path}"
    if actual_branch.strip() != branch:
        return None, (
            f"registered lane branch {branch!r} does not match "
            f"worktree branch {actual_branch.strip()!r}"
        )
    dirty = _git(
        ["status", "--porcelain", "--untracked-files=all"],
        raw_path,
    )
    if dirty is None:
        return None, f"git could not verify lane cleanliness at {raw_path}"
    if dirty.strip():
        detail = "\n".join(dirty.strip().splitlines()[:20])
        return None, (
            "the registered lane is not clean; preserve or commit modified "
            f"tracked and untracked files before retrying:\n{detail}"
        )
    return _attestation(EVIDENCE_WORKTREE_CLEAN), None


__all__ = [
    "EVIDENCE_MERGED_AND_REMOVED",
    "EVIDENCE_WORKTREE_CLEAN",
    "attest_releasable_lane",
]

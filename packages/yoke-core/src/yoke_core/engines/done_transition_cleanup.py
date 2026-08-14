"""Fail-closed cleanup for a completed item merge lane."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.backlog_session_attribution import _current_session_id
from yoke_core.engines.merge_landed_lane_cleanup import prune_landed_lane
from yoke_core.engines.remote_branch_cleanup import delete_remote_branch_if_merged


def _parent():
    from yoke_core.engines import done_transition as _dt

    return _dt


def _has_foreign_claim(item_id: int) -> bool:
    """Treat another owner or an unreadable claim registry as active.

    Relays ``claims.work.holder_list`` (its item filter is the exact active
    item-claim query this gate used) so the read runs over an https control
    plane as well as a local Postgres connection. Cleanup must fail closed:
    a refused relay or a transport error reads as "a claim is active" (True),
    preserving the bare-connect ``except: return True`` behavior so a git
    prune never proceeds on an unreadable claim registry.
    """
    caller = _current_session_id()
    try:
        resp = call_dispatcher(
            function_id="claims.work.holder_list",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={"item_id": int(item_id)},
        )
    except Exception:  # noqa: BLE001 - cleanup must fail closed
        return True
    if not resp.success:
        return True
    holders = {
        str(holder.get("session_id") or "")
        for holder in (resp.result or {}).get("holders", [])
    }
    return bool(holders and (not caller or holders != {caller}))


def _branch_exists(project_repo: Path, branch: str) -> bool:
    result = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", branch],
        capture=True,
    )
    return result.returncode == 0


def _branch_merged(project_repo: Path, branch: str, base_ref: str) -> bool:
    result = _parent()._run_git(
        [
            "-C",
            str(project_repo),
            "merge-base",
            "--is-ancestor",
            branch,
            base_ref,
        ],
        capture=True,
    )
    return result.returncode == 0


def _delete_remote_for_lane(project_repo: Path, branch: str, base_branch: str) -> bool:
    """Prove and delete one remote via the shared leased helper."""
    result = delete_remote_branch_if_merged(
        run_git=lambda command: _parent()._run_git(
            ["-C", str(project_repo), *command],
            capture=True,
        ),
        branch=branch,
        target_branch=base_branch,
    )
    if result.status == "deleted":
        print(f"  Deleted merged remote branch: origin/{branch}")
    elif result.status == "preserved":
        print(f"  Preserving remote branch origin/{branch}: {result.reason}")
    return result.cleanup_complete


def _cleanup_stale_branches(
    item_id: int,
    lane_branch: str,
    project_repo: Path,
    base_branch: str = "main",
    authority_block: str = "",
) -> bool:
    """Run the shared proof-gated cleanup after status reaches ``done``."""
    print("\n=== Terminal lane cleanup ===")

    if authority_block:
        print(f"  Preserving merge lane: {authority_block}.")
        return False

    if lane_branch:
        valid_branch = _parent()._run_git(
            [
                "-C",
                str(project_repo),
                "check-ref-format",
                "--branch",
                lane_branch,
            ],
            capture=True,
        )
        if valid_branch.returncode != 0:
            print(
                "  Preserving merge lane: the recorded branch is not valid "
                f"({lane_branch!r})."
            )
            return False

    from yoke_core.domain.worktree_naming import worktree_name_for_item

    branch = lane_branch or worktree_name_for_item(None, item_id)
    if not _branch_exists(project_repo, branch):
        return _delete_remote_for_lane(project_repo, branch, base_branch)

    def run_git(command, *, cwd=None, capture=True):
        return _parent()._run_git(["-C", str(project_repo), *command], capture=capture)

    try:
        preserved = prune_landed_lane(
            repo_root=str(project_repo),
            branch=branch,
            target=base_branch,
            item_id=item_id,
            run_git=run_git,
            emit=lambda message, **_kw: print(f"  {message}"),
        )
    except Exception as exc:  # noqa: BLE001 - terminal state is already committed
        print(f"  Preserving merge lane after an unexpected cleanup refusal: {exc}")
        return False
    for reason in preserved:
        print(
            f"  item {item_id}, path {project_repo / '.worktrees' / branch}: {reason}"
        )
    if (
        lane_branch.startswith("trial/")
        and not preserved
        and not _cleanup_trial_branches(project_repo, item_id=item_id)
    ):
        return False
    return not preserved


def _cleanup_trial_branches(project_repo: Path, item_id: int | None = None) -> bool:
    """Delete only trial refs whose tips are already retained by ``HEAD``."""
    pattern = f"trial/YOK-{item_id}" if item_id is not None else "trial/*"
    branches = _parent()._run_git(
        ["-C", str(project_repo), "branch", "--list", pattern],
        capture=True,
    )
    complete = branches.returncode == 0
    for line in (branches.stdout or "").splitlines():
        ref = line.strip().lstrip("* ")
        match = re.fullmatch(r"trial/YOK-(\d+)", ref)
        if not match:
            continue
        trial_item = int(match.group(1))
        if _parent()._query_item_field(trial_item, "status") != "done":
            complete = False
            continue
        if _has_foreign_claim(trial_item):
            complete = False
            continue
        if not _branch_merged(project_repo, ref, "HEAD"):
            print(f"  Preserving trial branch with unique commits: {ref}")
            complete = False
            continue
        deleted = _parent()._run_git(
            ["-C", str(project_repo), "branch", "-d", ref],
            capture=True,
        )
        if deleted.returncode != 0:
            complete = False
            print(
                f"  WARNING: Refused to delete trial branch {ref}",
                file=sys.stderr,
            )
    return complete


__all__ = [
    "_cleanup_stale_branches",
    "_cleanup_trial_branches",
    "_has_foreign_claim",
]

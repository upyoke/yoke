"""``yoke item-worktrees ...`` flag adapters."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    item_target,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
    emit_response,
)
from yoke_contracts.item_worktrees import EVIDENCE_ONLY_RECOVERY_REASON


ITEM_WORKTREES_GET_USAGE = (
    "yoke item-worktrees get <PREFIX-N> [--lane-role ROLE] "
    "[--field branch|path|lane-role|state|id] "
    "[--session-id S] [--json]"
)
ITEM_WORKTREES_RELEASE_USAGE = (
    "yoke item-worktrees release <PREFIX-N> --all-active "
    f"--reason {EVIDENCE_ONLY_RECOVERY_REASON} "
    "[--session-id S] [--json]"
)


def _local_error(code: str, message: str) -> int:
    print(
        json.dumps({"success": False, "code": code, "message": message}),
        file=sys.stderr,
    )
    return 1


def _attest_clean_lane(worktree: object) -> tuple[dict | None, str | None]:
    """Prove the registered lane path is the matching, fully clean worktree."""
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
    if not path.is_absolute() or not path.is_dir():
        return (
            None,
            f"the registered lane path is not an accessible directory: {raw_path}",
        )

    try:
        branch_result = subprocess.run(
            ["git", "-C", raw_path, "rev-parse", "--abbrev-ref", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if branch_result.returncode != 0:
            return None, f"git could not verify the registered lane path: {raw_path}"
        actual_branch = branch_result.stdout.strip()
        if actual_branch != branch:
            return None, (
                f"registered lane branch {branch!r} does not match "
                f"worktree branch {actual_branch!r}"
            )
        status_result = subprocess.run(
            [
                "git",
                "-C",
                raw_path,
                "status",
                "--porcelain",
                "--ignored=matching",
                "--untracked-files=all",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return None, f"git cleanliness verification could not run: {exc}"
    if status_result.returncode != 0:
        return None, f"git could not verify lane cleanliness at {raw_path}"
    dirty = status_result.stdout.strip()
    if dirty:
        detail = "\n".join(dirty.splitlines()[:20])
        return None, (
            "the registered lane is not clean; preserve or commit modified "
            f"tracked, untracked, and ignored files before retrying:\n{detail}"
        )
    return {
        "worktree_id": worktree_id,
        "branch": branch,
        "path": raw_path,
        "observed_clean": True,
    }, None


def item_worktrees_get(args: List[str]) -> int:
    """Read one active item-owned worktree lane."""
    parser = argparse.ArgumentParser(
        prog="yoke item-worktrees get",
        description=ITEM_WORKTREES_GET_USAGE,
    )
    parser.add_argument(
        "item",
        help="Item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--lane-role",
        default="implementation",
        help="Active lane role to read (default: implementation).",
    )
    parser.add_argument(
        "--field",
        choices=("branch", "path", "lane-role", "state", "id"),
        default="branch",
        help="Lane field to print in human mode (default: branch).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEM_WORKTREES_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        if not response.success:
            return None
        worktree = (response.result or {}).get("worktree")
        if not isinstance(worktree, dict):
            return None
        value = worktree.get(parsed.field.replace("-", "_"))
        if value is not None:
            print(value, file=stdout)
        return None

    return dispatch_and_emit(
        function_id="item_worktrees.get",
        target=item_target("item", parsed.item, parsed.project),
        payload={"lane_role": parsed.lane_role},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def item_worktrees_release(args: List[str]) -> int:
    """Release every active lane for one claimed item."""
    parser = argparse.ArgumentParser(
        prog="yoke item-worktrees release",
        description=ITEM_WORKTREES_RELEASE_USAGE,
    )
    parser.add_argument(
        "item",
        help="Item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--all-active",
        action="store_true",
        required=True,
        help="Release every active lane owned by this item.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        choices=(EVIDENCE_ONLY_RECOVERY_REASON,),
        help="Auditable reason for releasing the active lanes.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        ITEM_WORKTREES_RELEASE_USAGE,
    )
    if parsed is None:
        return 2

    target = item_target("item", parsed.item, parsed.project)
    ensure_handlers_loaded()
    read_response = call_dispatcher(
        function_id="item_worktrees.get",
        target=target,
        payload={"lane_role": "implementation"},
        actor=build_actor(session_id=parsed.session_id),
    )
    if not read_response.success:
        return emit_response(read_response, json_mode=parsed.json_mode)
    worktree = (read_response.result or {}).get("worktree")
    attestation, error = _attest_clean_lane(worktree)
    if error is not None:
        return _local_error("worktree_cleanliness_unverified", error)

    payload = {
        "all_active": parsed.all_active,
        "reason": parsed.reason,
    }
    if attestation is not None:
        payload["clean_lane_attestation"] = attestation
    return dispatch_and_emit(
        function_id="item_worktrees.release",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "ITEM_WORKTREES_GET_USAGE",
    "ITEM_WORKTREES_RELEASE_USAGE",
    "item_worktrees_get",
    "item_worktrees_release",
]

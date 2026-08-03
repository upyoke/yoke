"""``yoke item-worktrees ...`` flag adapters."""

from __future__ import annotations

import argparse
import json
import sys
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
from yoke_cli.commands.adapters.item_worktree_lane_evidence import (
    attest_releasable_lane,
)
from yoke_contracts.item_worktrees import EVIDENCE_ONLY_RECOVERY_REASON


ITEM_WORKTREES_GET_USAGE = (
    "yoke item-worktrees get <PREFIX-N> [--lane-role ROLE] "
    "[--field branch|path|lane-role|state|id] "
    "[--session-id S] [--json]"
)
ITEM_WORKTREES_LIST_USAGE = (
    "yoke item-worktrees list <PREFIX-N> "
    "[--project P] [--session-id S] [--json]"
)
ITEM_WORKTREES_PATH_RECORD_USAGE = (
    "yoke item-worktrees path-record <PREFIX-N> --worktree-id ID "
    "--branch BRANCH --path ABSOLUTE_PATH "
    "[--project P] [--session-id S] [--json]"
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


def item_worktrees_list(args: List[str]) -> int:
    """Read every active item-owned worktree lane."""
    parser = argparse.ArgumentParser(
        prog="yoke item-worktrees list",
        description=ITEM_WORKTREES_LIST_USAGE,
    )
    parser.add_argument(
        "item",
        help="Item id (PREFIX-N or project-local number).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEM_WORKTREES_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        for lane in (response.result or {}).get("worktrees") or []:
            print(
                "|".join([
                    str(lane.get("id") or ""),
                    str(lane.get("lane_role") or ""),
                    str(lane.get("branch") or ""),
                    str(lane.get("path") or ""),
                    str(lane.get("state") or ""),
                ]),
                file=stdout,
            )

    return dispatch_and_emit(
        function_id="item_worktrees.list",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def item_worktrees_path_record(args: List[str]) -> int:
    """Record a local path against an unchanged authoritative lane."""
    parser = argparse.ArgumentParser(
        prog="yoke item-worktrees path-record",
        description=ITEM_WORKTREES_PATH_RECORD_USAGE,
    )
    parser.add_argument(
        "item",
        help="Item id (PREFIX-N or project-local number).",
    )
    parser.add_argument("--worktree-id", type=int, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--path", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        ITEM_WORKTREES_PATH_RECORD_USAGE,
    )
    if parsed is None:
        return 2

    return dispatch_and_emit(
        function_id="item_worktrees.path_record",
        target=item_target("item", parsed.item, parsed.project),
        payload={"path": parsed.path},
        preconditions={
            "worktree_id": parsed.worktree_id,
            "branch": parsed.branch,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
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
    attestation, error = attest_releasable_lane(
        (read_response.result or {}).get("worktree"),
        target=target,
        session_id=parsed.session_id,
    )
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
    "ITEM_WORKTREES_LIST_USAGE",
    "ITEM_WORKTREES_PATH_RECORD_USAGE",
    "ITEM_WORKTREES_RELEASE_USAGE",
    "item_worktrees_get",
    "item_worktrees_list",
    "item_worktrees_path_record",
    "item_worktrees_release",
]

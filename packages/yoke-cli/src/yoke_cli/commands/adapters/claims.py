"""``yoke claims work|path ...`` flag adapters.

Covers four function ids:

* ``claims.work.acquire`` — ``yoke claims work acquire``
* ``claims.work.release`` — ``yoke claims work release``
* ``claims.path.register`` — ``yoke claims path register``
* ``claims.path.widen`` — ``yoke claims path widen``
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    split_comma,
    usage_error,
)
from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "claims_work_acquire", "claims_work_release",
    "claims_path_register", "claims_path_widen",
    "CLAIM_WORK_ACQUIRE_USAGE", "CLAIM_WORK_RELEASE_USAGE",
    "CLAIM_PATH_REGISTER_USAGE", "CLAIM_PATH_WIDEN_USAGE",
]


# ---------------------------------------------------------------------------
# claims.work.acquire / release
# ---------------------------------------------------------------------------

CLAIM_WORK_ACQUIRE_USAGE = (
    "yoke claims work acquire (--item PREFIX-N | --epic-id N --task-num N | "
    "--process KEY) [--reason TEXT] [--session-id S] [--json]"
)


def claims_work_acquire(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims work acquire",
        description=CLAIM_WORK_ACQUIRE_USAGE,
    )
    parser.add_argument("--item", default=None,
                        help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--epic-id", default=None,
                        help="Parent epic id for an epic-task claim.")
    parser.add_argument("--task-num", default=None,
                        help="Task number within the epic.")
    parser.add_argument("--process", default=None,
                        help="Process key for a process claim.")
    parser.add_argument("--project", default=None,
                        help="Project context for bare numeric item refs.")
    parser.add_argument("--reason", default=None,
                        help="Optional intent / rationale.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_WORK_ACQUIRE_USAGE)
    if parsed is None:
        return 2

    target_ref: TargetRef
    target_spec: Dict[str, Any]
    if parsed.item is not None:
        # The dispatcher resolves the raw ref into target.item_id; the
        # acquire handler reads it from the envelope target (relay shape).
        target_ref = item_target("item", parsed.item, parsed.project)
        target_spec = {"kind": "item"}
    elif parsed.epic_id is not None and parsed.task_num is not None:
        try:
            epic_id = int(parsed.epic_id)
            task_num = int(parsed.task_num)
        except ValueError:
            return usage_error("--epic-id and --task-num must be integers")
        target_ref = TargetRef(kind="epic_task", epic_id=epic_id, task_num=task_num)
        target_spec = {"kind": "epic_task", "epic_id": epic_id, "task_num": task_num}
    elif parsed.process is not None:
        # conflict_group is registry-computed server-side
        # (work_processes.conflict_group_for); callers never supply it.
        target_ref = TargetRef(kind="global")
        target_spec = {
            "kind": "process",
            "process_key": parsed.process,
            "project": parsed.project or "yoke",
        }
    else:
        return usage_error(
            "one of --item / --epic-id+--task-num / --process is required"
        )

    payload: Dict[str, Any] = {"target": target_spec}
    if parsed.reason:
        payload["reason"] = parsed.reason
    return dispatch_and_emit(
        function_id="claims.work.acquire",
        target=target_ref,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


CLAIM_WORK_RELEASE_USAGE = (
    "yoke claims work release "
    "(--claim-id N | --item PREFIX-N | --epic-id N --task-num N | --all-mine) "
    "[--reason TEXT] [--session-id S] [--json]\n"
    "  --epic-id + --task-num release the calling session's active "
    "epic_task claim on (epic_id, task_num).\n"
    "  --all-mine releases every active claim this session holds, without "
    "ending the session (harness owns session lifecycle)."
)

_SELECTOR_ERR = (
    "exactly one of --claim-id, --item, --epic-id+--task-num, or "
    "--all-mine is required"
)


def claims_work_release(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims work release",
        description=CLAIM_WORK_RELEASE_USAGE,
    )
    parser.add_argument("--claim-id", default=None,
                        help="work_claims.id to release.")
    parser.add_argument("--item", default=None,
                        help="Release this session's active claim on the item.")
    parser.add_argument("--epic-id", default=None,
                        help="Parent epic id (pair with --task-num).")
    parser.add_argument("--task-num", default=None,
                        help="Task number within the epic (pair with --epic-id).")
    parser.add_argument(
        "--all-mine", action="store_true",
        help=("Release every active claim this session still holds without "
              "ending the session (canonical reason "
              "'agent_handoff_session_scoped')."),
    )
    parser.add_argument(
        "--reason", default=None,
        help="Required with --claim-id, --item, or --epic-id+--task-num.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_WORK_RELEASE_USAGE)
    if parsed is None:
        return 2

    epic_id_set = parsed.epic_id is not None
    task_num_set = parsed.task_num is not None
    if epic_id_set != task_num_set:
        return usage_error(
            "--epic-id and --task-num must be provided together"
        )
    epic_task_selector = epic_id_set and task_num_set

    selector_count = sum(
        bool(x) for x in (
            parsed.claim_id is not None,
            parsed.item is not None,
            epic_task_selector,
            parsed.all_mine,
        )
    )
    if selector_count != 1:
        return usage_error(_SELECTOR_ERR)

    if parsed.all_mine:
        return dispatch_and_emit(
            function_id="claims.work.release_session_scoped",
            target=TargetRef(kind="global"),
            payload={},
            session_id=parsed.session_id,
            json_mode=parsed.json_mode,
        )

    if not parsed.reason:
        return usage_error(
            "--reason is required when releasing by --claim-id, --item, "
            "or --epic-id+--task-num"
        )

    # The dispatcher's self_only verification resolves the calling
    # session's active claim for item / epic_task shaped targets, so the
    # client never pre-reads work_claims (relay contract).
    target_ref: TargetRef
    payload: Dict[str, Any] = {"reason": parsed.reason}
    if parsed.claim_id is not None:
        try:
            claim_id = int(parsed.claim_id)
        except ValueError:
            return usage_error("--claim-id must be an integer")
        target_ref = TargetRef(kind="claim", claim_id=claim_id)
        payload["claim_id"] = claim_id
    elif parsed.item is not None:
        target_ref = item_target(
            "item", parsed.item, getattr(parsed, "project", None),
        )
    else:
        try:
            epic_id = int(parsed.epic_id)
            task_num = int(parsed.task_num)
        except ValueError:
            return usage_error(
                "--epic-id and --task-num must be integers"
            )
        target_ref = TargetRef(
            kind="epic_task", epic_id=epic_id, task_num=task_num,
        )

    return dispatch_and_emit(
        function_id="claims.work.release",
        target=target_ref,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# claims.path.register / widen
# ---------------------------------------------------------------------------

CLAIM_PATH_REGISTER_USAGE = (
    "yoke claims path register --item PREFIX-N --paths PATH1,PATH2,... "
    "[--mode exclusive|shared] [--exception-reason TEXT] [--allow-planned] "
    "[--integration-target NAME] [--session-id S] [--json]"
)


def claims_path_register(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path register",
        description=CLAIM_PATH_REGISTER_USAGE,
    )
    parser.add_argument("--item", required=True,
                        help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--paths", required=True,
                        help="Comma-separated list of repo-relative paths.")
    parser.add_argument("--mode", default="exclusive",
                        help="exclusive (default) or shared.")
    parser.add_argument("--exception-reason", default=None,
                        help="Reason text when claiming inside an exempt directory.")
    parser.add_argument("--allow-planned", action="store_true",
                        help="Permit claim registration for not-yet-committed paths.")
    parser.add_argument("--integration-target", default=None,
                        help="Override integration target classification (advanced).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_PATH_REGISTER_USAGE)
    if parsed is None:
        return 2

    payload: Dict[str, Any] = {
        "paths": split_comma(parsed.paths),
        "mode": parsed.mode,
        "allow_planned": bool(parsed.allow_planned),
    }
    if parsed.exception_reason:
        payload["exception_reason"] = parsed.exception_reason
    if parsed.integration_target:
        payload["integration_target"] = parsed.integration_target
    sync_local_snapshot_for_write(
        project=parsed.project,
        integration_target=parsed.integration_target,
        session_id=parsed.session_id,
    )
    return dispatch_and_emit(
        function_id="claims.path.register",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


CLAIM_PATH_WIDEN_USAGE = (
    "yoke claims path widen --claim-id N --add-paths PATH1,PATH2,... "
    "--reason TEXT --item PREFIX-N [--allow-planned] "
    "[--directory-paths PATH1,PATH2,...] [--session-id S] [--json]"
)


def claims_path_widen(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path widen",
        description=CLAIM_PATH_WIDEN_USAGE,
    )
    parser.add_argument("--claim-id", required=True, help="path_claims.id to widen.")
    parser.add_argument("--add-paths", required=True,
                        help="Comma-separated list of repo-relative paths to add.")
    parser.add_argument("--reason", required=True, help="Reason for widening.")
    parser.add_argument("--item", required=True,
                        help="Owning item id (PREFIX-N or project-local number); required for target ref.")
    parser.add_argument("--allow-planned", action="store_true",
                        help="Permit widen coverage over not-yet-committed paths.")
    parser.add_argument("--directory-paths", default=None,
                        help="Comma-separated subset of --add-paths to mark as "
                             "directory targets (requires --allow-planned).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_PATH_WIDEN_USAGE)
    if parsed is None:
        return 2

    try:
        claim_id = int(parsed.claim_id)
    except ValueError as exc:
        return usage_error(str(exc))

    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "add_paths": split_comma(parsed.add_paths),
        "reason": parsed.reason,
        "allow_planned": bool(parsed.allow_planned),
    }
    if parsed.directory_paths:
        payload["directory_paths"] = split_comma(parsed.directory_paths)
    sync_local_snapshot_for_write(
        project=parsed.project, integration_target=None,
        session_id=parsed.session_id,
    )
    return dispatch_and_emit(
        function_id="claims.path.widen",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )

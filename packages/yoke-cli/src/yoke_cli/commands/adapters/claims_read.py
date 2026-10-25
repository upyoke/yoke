"""Read work holders, path claims and conflict coordination evidence."""

from __future__ import annotations

import argparse
from yoke_cli.commands.adapters.claims_path_listing import (
    CLAIMS_PATH_LIST_USAGE as CLAIMS_PATH_LIST_USAGE,
    claims_path_list as claims_path_list,
)

from pathlib import Path
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_full_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    split_comma,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands.adapters.claims_conflicts_read import (
    PATH_CLAIMS_CONFLICTS_LIST_USAGE as PATH_CLAIMS_CONFLICTS_LIST_USAGE,
    path_claims_conflicts_list as path_claims_conflicts_list,
)

__all__ = [
    "claims_work_holder_get",
    "claims_work_holder_list",
    "claims_work_current",
    "claims_path_list",
    "claims_path_get",
    "claims_path_coordination_decision_build",
    "path_claims_conflicts_list",
    "CLAIM_WORK_HOLDER_GET_USAGE",
    "CLAIM_WORK_HOLDER_LIST_USAGE",
    "CLAIM_WORK_CURRENT_USAGE",
    "CLAIMS_PATH_LIST_USAGE",
    "CLAIMS_PATH_GET_USAGE",
    "CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE",
    "PATH_CLAIMS_CONFLICTS_LIST_USAGE",
]

CLAIMS_PATH_GET_USAGE = (
    "yoke claims path get CLAIM_ID [--full] [--session-id S] [--json]"
)


def claims_path_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path get",
        usage=CLAIMS_PATH_GET_USAGE,
    )
    parser.add_argument(
        "claim_id", metavar="CLAIM_ID", help="Path claim id (a number)."
    )
    add_full_arg(parser, "targets, bindings and amendment history")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIMS_PATH_GET_USAGE)
    if parsed is None:
        return 2
    try:
        claim_id = int(parsed.claim_id)
    except ValueError:
        return usage_error("CLAIM_ID must be an integer")

    def writer(response, out, err):
        from yoke_cli.transport.human_values import write_human

        result = response.result or {}
        if parsed.full:
            write_human(result, out)
            return
        claim = result.get("claim", result)
        write_human(
            {
                key: value
                for key, value in claim.items()
                if key
                not in {"declared_targets", "amendments", "task_bindings", "target_ids"}
            },
            out,
        )
        print(
            f"Full targets and history: yoke claims path get {claim_id} --full",
            file=out,
        )

    return dispatch_and_emit(
        function_id="claims.path.get",
        target=TargetRef(kind="path_claim", path_claim_id=claim_id),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=writer,
    )


CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE = (
    "yoke claims path coordination-decision-build (--item | --candidate-item) PREFIX-N "
    "--conflicting-claim CLAIM_ID --paths PATH1,PATH2,... [--project P] [--full] "
    "[--session-id S] [--json]"
)


def claims_path_coordination_decision_build(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path coordination-decision-build",
        usage=CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE,
    )
    parser.add_argument(
        "--item",
        "--candidate-item",
        dest="item",
        required=True,
        metavar="PREFIX-N",
        help="Item that wants the shared paths (PREFIX-N).",
    )
    parser.add_argument(
        "--conflicting-claim",
        required=True,
        metavar="CLAIM_ID",
        help="Id of the other item's open path claim on the same paths.",
    )
    parser.add_argument(
        "--paths",
        required=True,
        metavar="PATH1,PATH2,...",
        help="Comma-separated shared paths, relative to the repo root.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE,
    )
    if parsed is None:
        return 2
    try:
        claim_id = int(parsed.conflicting_claim)
    except ValueError:
        return usage_error("--conflicting-claim must be an integer")
    return dispatch_and_emit(
        function_id="claims.path.coordination_decision_build",
        target=item_target("item", parsed.item, parsed.project),
        payload={
            "conflicting_claim_id": claim_id,
            "shared_paths": split_comma(parsed.paths),
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


CLAIM_WORK_HOLDER_GET_USAGE = (
    "yoke claims work holder-get (--item PREFIX-N | PREFIX-N | "
    "--path ABSOLUTE_PATH) [--project P] [--full] [--session-id S] [--json]"
)


def claims_work_holder_get(args: List[str]) -> int:
    """Fetch the active work-claim holder, by item or by path."""
    parser = argparse.ArgumentParser(
        prog="yoke claims work holder-get",
        usage=CLAIM_WORK_HOLDER_GET_USAGE,
    )
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="Item id (PREFIX-N). Alternative to positional.",
    )
    parser.add_argument(
        "--path",
        default=None,
        metavar="ABSOLUTE_PATH",
        help=(
            "Absolute path. Answers who holds the worktree lane containing "
            "it — use this when you are standing in a directory and do not "
            "know which item owns it. An empty holder means no active "
            "claimed lane contains the path."
        ),
    )
    parser.add_argument(
        "item_positional",
        nargs="?",
        default=None,
        metavar="PREFIX-N",
        help="Item id (PREFIX-N); same as --item.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_WORK_HOLDER_GET_USAGE)
    if parsed is None:
        return 2
    raw_item = parsed.item or parsed.item_positional
    if parsed.path and raw_item:
        return usage_error("holder-get takes an item or --path, not both")
    if not raw_item and not parsed.path:
        return usage_error(
            "holder-get requires --item PREFIX-N, a positional item, "
            "or --path ABSOLUTE_PATH"
        )
    if parsed.path:
        return dispatch_and_emit(
            function_id="claims.work.holder_get",
            target=TargetRef(
                kind="global", project_id=client_project_context(parsed.project)
            ),
            payload={"path": str(Path(parsed.path).expanduser().resolve())},
            session_id=parsed.session_id,
            json_mode=parsed.json_mode,
        )
    return dispatch_and_emit(
        function_id="claims.work.holder_get",
        target=item_target("item", raw_item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


CLAIM_WORK_CURRENT_USAGE = (
    "yoke claims work current (--item PREFIX-N | PREFIX-N) [--project P] [--full] "
    "[--session-id S] [--json]"
)


def claims_work_current(args: List[str]) -> int:
    """Same read as ``holder-get`` by item: ``--item`` or a positional item."""
    parser = argparse.ArgumentParser(
        prog="yoke claims work current",
        usage=CLAIM_WORK_CURRENT_USAGE,
    )
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="Item id (PREFIX-N). Alternative to positional.",
    )
    parser.add_argument(
        "item_positional",
        nargs="?",
        default=None,
        metavar="PREFIX-N",
        help="Item id (PREFIX-N); same as --item.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_WORK_CURRENT_USAGE)
    if parsed is None:
        return 2
    raw_item = parsed.item or parsed.item_positional
    if not raw_item:
        return usage_error("current requires --item PREFIX-N or a positional item")
    return dispatch_and_emit(
        function_id="claims.work.holder_get",
        target=item_target("item", raw_item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


CLAIM_WORK_HOLDER_LIST_USAGE = (
    "yoke claims work holder-list (--item PREFIX-N | --session-id-filter S) "
    "[--project P] [--full] [--session-id S] [--json]"
)


def claims_work_holder_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims work holder-list",
        usage=CLAIM_WORK_HOLDER_LIST_USAGE,
    )
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="List this item's claims (PREFIX-N).",
    )
    parser.add_argument(
        "--session-id-filter",
        dest="session_id_filter",
        default=None,
        metavar="S",
        help="List this session's claims (--session-id names the caller).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_WORK_HOLDER_LIST_USAGE)
    if parsed is None:
        return 2
    if not parsed.item and not parsed.session_id_filter:
        return usage_error("holder-list requires --item or --session-id-filter")
    payload: Dict[str, Any] = {}
    if parsed.session_id_filter:
        payload["session_id"] = parsed.session_id_filter
    if parsed.item:
        target = item_target("item", parsed.item, parsed.project)
    else:
        target = TargetRef(
            kind="global", project_id=client_project_context(parsed.project)
        )
    return dispatch_and_emit(
        function_id="claims.work.holder_list",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )

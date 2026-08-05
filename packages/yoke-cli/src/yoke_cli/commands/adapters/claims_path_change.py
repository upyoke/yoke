"""CLI adapters for widening and amending registered path claims."""

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


CLAIM_PATH_WIDEN_USAGE = (
    "yoke claims path widen --claim-id N --add-paths PATH1,PATH2,... "
    "--reason TEXT --item PREFIX-N [--allow-planned] "
    "[--directory-paths PATH1,PATH2,...] [--session-id S] [--json]"
)
CLAIM_PATH_AMEND_USAGE = CLAIM_PATH_WIDEN_USAGE.replace(" path widen ", " path amend ")


def claims_path_widen(args: List[str]) -> int:
    return _claims_path_change(
        args,
        function_id="claims.path.widen",
        prog="yoke claims path widen",
        usage=CLAIM_PATH_WIDEN_USAGE,
    )


def claims_path_amend(args: List[str]) -> int:
    return _claims_path_change(
        args,
        function_id="claims.path.amend",
        prog="yoke claims path amend",
        usage=CLAIM_PATH_AMEND_USAGE,
    )


def _claims_path_change(
    args: List[str], *, function_id: str, prog: str, usage: str
) -> int:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    parser.add_argument("--claim-id", required=True, help="path_claims.id to change.")
    parser.add_argument(
        "--add-paths",
        required=True,
        help="Comma-separated list of repo-relative paths to add.",
    )
    parser.add_argument("--reason", required=True, help="Reason for the change.")
    parser.add_argument(
        "--item",
        required=True,
        help="Owning item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--allow-planned",
        action="store_true",
        help="Permit coverage over not-yet-committed paths.",
    )
    parser.add_argument(
        "--directory-paths",
        default=None,
        help="Comma-separated subset of --add-paths that are directory targets.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
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
        project=parsed.project,
        integration_target=None,
        session_id=parsed.session_id,
    )
    return dispatch_and_emit(
        function_id=function_id,
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "CLAIM_PATH_AMEND_USAGE",
    "CLAIM_PATH_WIDEN_USAGE",
    "claims_path_amend",
    "claims_path_widen",
]

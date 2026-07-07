"""Read-only claim adapters: work holders, path-claim list/get, conflicts.

* ``claims.work.holder_get`` — fetch the active work-claim holder for
  an item.
* ``claims.work.holder_list`` — list active work-claim holders by
  item-id or session-id filter.
* ``claims.path.list`` — rich projections of an item's path claims.
* ``claims.path.get`` — one path-claim projection by claim id.
* ``claims.path.coordination_decision_build`` — evidence for resolving an
  unresolved overlap before authoring a coordination edge.
* ``path_claims.conflicts.list`` — list cross-claim conflicts, optionally
  scoped to an integration target and / or an item filter.
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
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "claims_work_holder_get", "claims_work_holder_list",
    "claims_work_current",
    "claims_path_list", "claims_path_get",
    "claims_path_coordination_decision_build",
    "path_claims_conflicts_list",
    "CLAIM_WORK_HOLDER_GET_USAGE", "CLAIM_WORK_HOLDER_LIST_USAGE",
    "CLAIM_WORK_CURRENT_USAGE",
    "CLAIMS_PATH_LIST_USAGE", "CLAIMS_PATH_GET_USAGE",
    "CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE",
    "PATH_CLAIMS_CONFLICTS_LIST_USAGE",
]


CLAIMS_PATH_LIST_USAGE = (
    "yoke claims path list --item PREFIX-N "
    "[--state S]... [--session-id S] [--json]"
)


def claims_path_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path list",
        description=CLAIMS_PATH_LIST_USAGE,
    )
    parser.add_argument(
        "--item", required=True,
        help="Item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--state", action="append", default=None,
        help=(
            "Filter by state (planned/blocked/active/released/cancelled); "
            "repeatable and/or comma-separated. Default: all states."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIMS_PATH_LIST_USAGE)
    if parsed is None:
        return 2
    states: List[str] = []
    for raw in parsed.state or []:
        states.extend(split_comma(raw))
    payload: Dict[str, Any] = {}
    if states:
        payload["states"] = states
    return dispatch_and_emit(
        function_id="claims.path.list",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


CLAIMS_PATH_GET_USAGE = (
    "yoke claims path get CLAIM_ID [--session-id S] [--json]"
)


def claims_path_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path get",
        description=CLAIMS_PATH_GET_USAGE,
    )
    parser.add_argument("claim_id", help="Path-claim id (integer).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIMS_PATH_GET_USAGE)
    if parsed is None:
        return 2
    try:
        claim_id = int(parsed.claim_id)
    except ValueError:
        return usage_error("CLAIM_ID must be an integer")
    return dispatch_and_emit(
        function_id="claims.path.get",
        target=TargetRef(kind="path_claim", path_claim_id=claim_id),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE = (
    "yoke claims path coordination-decision-build --item PREFIX-N "
    "--conflicting-claim CLAIM_ID --paths PATH1,PATH2,... "
    "[--session-id S] [--json]"
)


def claims_path_coordination_decision_build(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path coordination-decision-build",
        description=CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE,
    )
    parser.add_argument(
        "--item", "--candidate-item", dest="item", required=True,
        help="Candidate item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--conflicting-claim", required=True,
        help="path_claims.id of the non-terminal overlapping claim.",
    )
    parser.add_argument(
        "--paths", required=True,
        help="Comma-separated shared repo-relative paths.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, CLAIMS_PATH_COORDINATION_DECISION_BUILD_USAGE,
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
    "yoke claims work holder-get (--item PREFIX-N | PREFIX-N) "
    "[--session-id S] [--json]"
)


def claims_work_holder_get(args: List[str]) -> int:
    """Fetch the active work-claim holder; ``--item`` flag or positional."""
    parser = argparse.ArgumentParser(
        prog="yoke claims work holder-get",
        description=CLAIM_WORK_HOLDER_GET_USAGE,
    )
    parser.add_argument(
        "--item", default=None,
        help="Item id (PREFIX-N or project-local number). Alternative to positional.",
    )
    parser.add_argument(
        "item_positional", nargs="?", default=None,
        help="Item id positional (alternative to --item).",
    )
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIM_WORK_HOLDER_GET_USAGE)
    if parsed is None:
        return 2
    raw_item = parsed.item or parsed.item_positional
    if not raw_item:
        return usage_error("holder-get requires --item PREFIX-N or a positional item")
    return dispatch_and_emit(
        function_id="claims.work.holder_get",
        target=item_target("item", raw_item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


CLAIM_WORK_CURRENT_USAGE = (
    "yoke claims work current (--item PREFIX-N | PREFIX-N) [--session-id S] [--json]"
)


def claims_work_current(args: List[str]) -> int:
    """Alias for ``holder-get`` accepting both ``--item`` flag and positional.

    ``yoke claims work current --item PREFIX-N`` is the intuitive
    current-claim inspection surface. Routes to the same
    ``claims.work.holder_get`` function id as ``holder-get`` — distinct
    only in CLI ergonomics (``--item`` flag plus positional fallback so
    either shape works).
    """
    parser = argparse.ArgumentParser(
        prog="yoke claims work current",
        description=CLAIM_WORK_CURRENT_USAGE,
    )
    parser.add_argument(
        "--item", default=None,
        help="Item id (PREFIX-N or project-local number). Alternative to positional.",
    )
    parser.add_argument(
        "item_positional", nargs="?", default=None,
        help="Item id positional (alternative to --item).",
    )
    add_session_arg(parser); add_json_arg(parser)
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
    "[--session-id S] [--json]"
)


def claims_work_holder_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims work holder-list",
        description=CLAIM_WORK_HOLDER_LIST_USAGE,
    )
    parser.add_argument(
        "--item", default=None,
        help="Item id filter (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--session-id-filter", dest="session_id_filter", default=None,
        help="Session id filter (distinct from --session-id which is the caller's).",
    )
    add_session_arg(parser); add_json_arg(parser)
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
        target = TargetRef(kind="global")
    return dispatch_and_emit(
        function_id="claims.work.holder_list",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


PATH_CLAIMS_CONFLICTS_LIST_USAGE = (
    "yoke path-claims conflicts list [--integration-target NAME] "
    "[--item PREFIX-N] [--session-id S] [--json]"
)


def path_claims_conflicts_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke path-claims conflicts list",
        description=PATH_CLAIMS_CONFLICTS_LIST_USAGE,
    )
    parser.add_argument(
        "--integration-target", dest="integration_target", default=None,
        help="Filter to a specific integration target (e.g. 'main').",
    )
    parser.add_argument(
        "--item", default=None,
        help="Optional item filter (PREFIX-N or project-local number).",
    )
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PATH_CLAIMS_CONFLICTS_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.integration_target:
        payload["integration_target"] = parsed.integration_target
    if parsed.item:
        target = item_target("item", parsed.item, parsed.project)
    else:
        target = TargetRef(kind="global")
    return dispatch_and_emit(
        function_id="path_claims.conflicts.list",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )

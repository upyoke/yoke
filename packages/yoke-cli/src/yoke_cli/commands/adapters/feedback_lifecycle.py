"""``yoke ouroboros`` write/lifecycle adapters."""

from __future__ import annotations

import argparse
from yoke_cli.transport.human_values import write_human
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


OUROBOROS_ENTRY_MARK_REVIEWED_USAGE = (
    "yoke ouroboros entry mark-reviewed "
    "(ENTRY_ID | --before YYYY-MM-DD) "
    "[--limit N] [--include-unattributed] "
    "[--project P] [--session-id S] [--json]"
)
OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE = (
    "yoke ouroboros entry mark-archived (--all-reviewed | ENTRY_ID) "
    "[--include-unattributed] [--project P] [--session-id S] [--json]"
)
# A cutoff or all-reviewed selector always runs against one named project;
# without one it would sweep every project's queue in a single call.
_BULK_PROJECT_REQUIRED = (
    "project context required for a bulk selector: pass --project P, "
    "set YOKE_PROJECT, or run from a registered checkout"
)
_INCLUDE_UNATTRIBUTED_HELP = (
    "Also cover entries that belong to no project. They are left alone by "
    "default so one project's run never sweeps the universe-wide backlog."
)
__all__ = [
    "feedback_review",
    "feedback_archive",
    "OUROBOROS_ENTRY_MARK_REVIEWED_USAGE",
    "OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE",
]


def feedback_review(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry mark-reviewed",
        usage=OUROBOROS_ENTRY_MARK_REVIEWED_USAGE,
    )
    parser.add_argument(
        "entry_id",
        nargs="?",
        type=int,
        help="Entry id to mark reviewed.",
    )
    parser.add_argument(
        "--before",
        help=(
            "Review this project's unreviewed entries in any category "
            "created before this ISO date."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum entries to review in this bounded call.",
    )
    parser.add_argument(
        "--include-unattributed",
        action="store_true",
        help=_INCLUDE_UNATTRIBUTED_HELP,
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        OUROBOROS_ENTRY_MARK_REVIEWED_USAGE,
    )
    if parsed is None:
        return 2
    selectors = (parsed.entry_id, parsed.before)
    if sum(selector is not None for selector in selectors) != 1:
        return usage_error(
            "pass exactly one of ENTRY_ID, --before,"
        )
    if parsed.entry_id is not None and parsed.limit is not None:
        return usage_error("--limit requires --before")
    if parsed.entry_id is not None and parsed.include_unattributed:
        return usage_error(
            "--include-unattributed requires --before; "
            "an entry id already names the one entry to review"
        )

    payload: Dict[str, Any] = {}
    if parsed.entry_id is not None:
        payload["entry_id"] = parsed.entry_id
    elif parsed.before is not None:
        payload["before"] = parsed.before
        if parsed.limit is not None:
            payload["limit"] = parsed.limit
    if parsed.include_unattributed:
        payload["include_unattributed"] = True
    # The entry row is the write authority; this project only confirms it,
    # and supplies authority for an entry that belongs to no project. A bulk
    # selector has no row to read, so it must be named.
    project = client_project_context(parsed.project)
    if project:
        payload["project"] = project
    elif parsed.entry_id is None:
        return usage_error(_BULK_PROJECT_REQUIRED)

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="ouroboros.entry.mark_reviewed",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def feedback_archive(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry mark-archived",
        usage=OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE,
    )
    parser.add_argument("entry_id", nargs="?", type=int, help="Entry id to archive.")
    parser.add_argument(
        "--all-reviewed",
        action="store_true",
        help="Archive every reviewed entry.",
    )
    parser.add_argument(
        "--include-unattributed",
        action="store_true",
        help=_INCLUDE_UNATTRIBUTED_HELP,
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE,
    )
    if parsed is None:
        return 2
    if parsed.all_reviewed and parsed.entry_id is not None:
        return usage_error("pass either --all-reviewed or ENTRY_ID, not both")
    if not parsed.all_reviewed and parsed.entry_id is None:
        return usage_error("pass --all-reviewed or ENTRY_ID")
    if parsed.include_unattributed and not parsed.all_reviewed:
        return usage_error(
            "--include-unattributed requires --all-reviewed; an entry id "
            "already names the one entry to archive"
        )
    payload = {"all_reviewed": bool(parsed.all_reviewed)}
    if parsed.entry_id is not None:
        payload["entry_id"] = parsed.entry_id
    if parsed.include_unattributed:
        payload["include_unattributed"] = True
    # The entry row is the write authority; this project only confirms it,
    # and supplies authority for an entry that belongs to no project. A bulk
    # selector has no row to read, so it must be named.
    project = client_project_context(parsed.project)
    if project:
        payload["project"] = project
    elif parsed.all_reviewed:
        return usage_error(_BULK_PROJECT_REQUIRED)

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="ouroboros.entry.mark_archived",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )

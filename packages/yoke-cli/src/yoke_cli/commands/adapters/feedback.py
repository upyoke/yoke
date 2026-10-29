"""Feedback filing and reading adapters."""

from __future__ import annotations

import argparse
from yoke_cli.commands.adapters.list_paging import add_page_args, dispatch_list

from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import (
    add_stdin_flag,
    add_text_file_pair,
    resolve_one_text_source,
)
from yoke_contracts.field_note_text import (
    CORRELATION_ID_HELP,
    EVIDENCE_MAX_CHARS,
    HELP_BODY,
    KIND_VALUES,
)
from yoke_contracts.session_identity import resolve_actor_role
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "feedback_append",
    "feedback_list",
    "feedback_get",
    "OUROBOROS_USAGE",
    "OUROBOROS_FIELD_NOTE_LIST_USAGE",
    "OUROBOROS_FIELD_NOTE_GET_USAGE",
]


OUROBOROS_FIELD_NOTE_LIST_USAGE = (
    "yoke feedback list [--unreviewed] [--project P] "
    "[--scope universe|project|unscoped] [--category C] [--limit N] [--offset N] [--count] [--full] [--session-id S] [--json]"
)


def feedback_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke feedback list",
        usage=OUROBOROS_FIELD_NOTE_LIST_USAGE,
    )
    parser.add_argument(
        "--unreviewed",
        action="store_true",
        help="Only notes not yet reviewed or archived.",
    )
    parser.add_argument(
        "--project",
        default=None,
        metavar="P",
        help=(
            "Project slug or id to list (default: --project, then "
            "$YOKE_PROJECT, then this checkout's project)."
        ),
    )
    parser.add_argument("--scope", choices=("universe", "project", "unscoped"), default="universe", help="Visible notes across the universe, one project, or no project.")
    parser.add_argument("--category", choices=KIND_VALUES, help="Only notes in this category.")
    add_page_args(parser, limit=None, offset=None, page_size=50)
    parser.add_argument(
        "--count",
        action="store_true",
        help="Print how many notes match instead of the notes.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_FIELD_NOTE_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"scope": parsed.scope}
    if parsed.category:
        payload["category"] = parsed.category
    if parsed.unreviewed:
        payload["unreviewed"] = True
    # Same client ladder as append: --project, then YOKE_PROJECT, then the
    # machine-config checkout map. Unmapped directories omit the hint.
    project = client_project_context(parsed.project)
    if project:
        payload["project"] = project
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    if parsed.offset is not None:
        payload["offset"] = parsed.offset
    if parsed.count:
        payload["count"] = True
    return dispatch_list(
        parsed=parsed,
        function_id="ouroboros.field_note.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


OUROBOROS_FIELD_NOTE_GET_USAGE = (
    "yoke feedback get ENTRY_ID [--full] [--session-id S] [--json]"
)


def feedback_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke feedback get",
        usage=OUROBOROS_FIELD_NOTE_GET_USAGE,
    )
    parser.add_argument(
        "entry_id", metavar="ENTRY_ID", help="Field note id (a number)."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_FIELD_NOTE_GET_USAGE)
    if parsed is None:
        return 2
    try:
        entry_id = int(parsed.entry_id)
    except ValueError:
        return usage_error("ENTRY_ID must be an integer")
    return dispatch_and_emit(
        function_id="ouroboros.field_note.get",
        target=TargetRef(kind="global"),
        payload={
            "entry_id": entry_id,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )



OUROBOROS_USAGE = (
    "yoke feedback "
    "--to yoke|universe --category failed|new|unclear|observation|idea "
    "(--evidence TEXT | --evidence-file PATH | --stdin) [--corrects ENTRY_ID] "
    "[--target-project P] [--correlation-id ID] [--session-id S] [--json]"
)


def feedback_append(args: List[str]) -> int:
    # --help body is yoke_contracts.field_note_text.HELP_BODY.
    # RawDescriptionHelpFormatter preserves that multi-line layout.
    parser = argparse.ArgumentParser(
        prog="yoke feedback",
        usage=OUROBOROS_USAGE,
        description=HELP_BODY,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--category",
        required=True,
        choices=KIND_VALUES,
        help="What kind of problem this is; the kinds are described above.",
    )
    parser.add_argument("--to", choices=("yoke", "universe"), required=True, help="Send Yoke issues to Yoke or project findings to your universe.")
    evidence_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        evidence_group,
        "--evidence",
        "--evidence-file",
        dest="evidence",
        help_text=f"What happened, at most {EVIDENCE_MAX_CHARS} characters.",
        file_help="Read the evidence from a file.",
    )
    add_stdin_flag(
        evidence_group,
        help_text="Read the evidence from stdin, e.g. a quoted heredoc: <<'EOF'.",
    )
    parser.add_argument(
        "--corrects",
        dest="corrects",
        type=int,
        default=None,
        metavar="ENTRY_ID",
        help=(
            "Id of an earlier note of yours that this one replaces, because "
            "its evidence, kind or diagnosis was wrong. The earlier note "
            "leaves the unreviewed list. For a different problem, file a "
            "new note instead."
        ),
    )
    parser.add_argument(
        "--target-project",
        dest="target_project",
        default=None,
        metavar="P",
        help=(
            "Project the fix belongs in, when it is not this checkout's "
            "project. This checkout's project is recorded either way. "
            "Leave it off when you cannot tell; the note's work item then "
            "goes to this checkout's project, which can be changed later."
        ),
    )
    parser.add_argument(
        "--correlation-id",
        dest="correlation_id",
        default=None,
        metavar="ID",
        help=CORRELATION_ID_HELP,
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_USAGE)
    if parsed is None:
        return 2

    try:
        evidence = resolve_one_text_source(
            positional=parsed.evidence,
            file_path=parsed.evidence_file,
            stdin=parsed.stdin,
            positional_label="--evidence",
            file_flag="--evidence-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))

    if not evidence or not evidence.strip():
        return usage_error("--evidence must be non-empty")

    from yoke_cli.feedback_reporter import reporter_context
    metadata = reporter_context(parsed.session_id)
    payload: Dict[str, Any] = {"category": parsed.category, "evidence": evidence, "reporter_email": metadata.get("reporter_email")}
    if parsed.to == "yoke":
        if parsed.correlation_id or parsed.corrects is not None or parsed.target_project:
            return usage_error("feedback_public_options_invalid: public feedback accepts evidence and category; put references to prior public notes in the evidence. Project routing and correction links apply to --to universe.")
        from yoke_cli.feedback_delivery import send_feedback
        return send_feedback(category=parsed.category, evidence=evidence,
                             metadata=metadata, agent=resolve_actor_role() or metadata.get("agent"), json_mode=parsed.json_mode)
    if parsed.correlation_id:
        payload["correlation_id"] = parsed.correlation_id
    if parsed.corrects is not None:
        payload["corrects"] = parsed.corrects
    if parsed.target_project:
        payload["target_project"] = parsed.target_project
    # The dispatched-subagent role is only observable here, in the calling
    # process; the write handler runs server-side and cannot see it.
    actor_role = resolve_actor_role()
    if actor_role:
        payload["actor_role"] = actor_role
    # Same client ladder as listing/create: YOKE_PROJECT, then the
    # machine-config checkout→project map. The server never sees cwd, so
    # the checkout project must ride on the payload. Unmapped directories
    # omit the hint and keep session/global attribution.
    checkout_project = client_project_context()
    if checkout_project:
        payload["project"] = checkout_project
    return dispatch_and_emit(
        function_id="ouroboros.field_note.append",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )

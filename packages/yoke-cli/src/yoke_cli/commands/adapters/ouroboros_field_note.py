"""``yoke ouroboros field-note …`` adapters.

The field-note channel's own CLI surface: one writer
(``ouroboros.field_note.append``) and two readers
(``ouroboros.field_note.list`` / ``.get``) that scope the shared ouroboros
entry table to the ``field-note-`` category prefix. Curate-loop entry
readers and ``scratch dispatch-inputs`` live in
:mod:`yoke_cli.commands.adapters.misc`.
"""

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
    CATEGORY_PREFIX,
    CORRELATION_ID_HELP,
    EVIDENCE_MAX_CHARS,
    HELP_BODY,
    KIND_VALUES,
)
from yoke_contracts.session_identity import resolve_actor_role
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "ouroboros_field_note_append",
    "ouroboros_field_note_list",
    "ouroboros_field_note_get",
    "OUROBOROS_USAGE",
    "OUROBOROS_FIELD_NOTE_LIST_USAGE",
    "OUROBOROS_FIELD_NOTE_GET_USAGE",
]

# ---------------------------------------------------------------------------
# ouroboros.field_note.list / ouroboros.field_note.get
# ---------------------------------------------------------------------------

OUROBOROS_FIELD_NOTE_LIST_USAGE = (
    "yoke ouroboros field-note list [--unreviewed] [--project P] "
    "[--limit N] [--offset N] [--count] [--full] [--session-id S] [--json]"
)


def ouroboros_field_note_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros field-note list",
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
    payload: Dict[str, Any] = {"category_prefix": CATEGORY_PREFIX}
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
    "yoke ouroboros field-note get ENTRY_ID [--full] [--session-id S] [--json]"
)


def ouroboros_field_note_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros field-note get",
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
            "category_prefix": CATEGORY_PREFIX,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# ouroboros.field_note.append
# ---------------------------------------------------------------------------

OUROBOROS_USAGE = (
    "yoke ouroboros field-note append "
    "--kind failed|new|unclear|observation "
    "(--evidence TEXT | --evidence-file PATH | --stdin) [--corrects ENTRY_ID] "
    "[--target-project P] [--correlation-id ID] [--session-id S] [--json]"
)


def ouroboros_field_note_append(args: List[str]) -> int:
    # --help body is yoke_contracts.field_note_text.HELP_BODY.
    # RawDescriptionHelpFormatter preserves that multi-line layout.
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros field-note append",
        usage=OUROBOROS_USAGE,
        description=HELP_BODY,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--kind",
        required=True,
        choices=KIND_VALUES,
        help="What kind of problem this is; the kinds are described above.",
    )
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

    payload: Dict[str, Any] = {"kind": parsed.kind, "evidence": evidence}
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

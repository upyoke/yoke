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
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_contracts.field_note_text import (
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

_FIELD_NOTE_CATEGORY_PREFIX = "field-note-"

OUROBOROS_FIELD_NOTE_LIST_USAGE = (
    "yoke ouroboros field-note list [--unreviewed] [--project P] "
    "[--limit N] [--session-id S] [--json]"
)


def ouroboros_field_note_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros field-note list",
        description=OUROBOROS_FIELD_NOTE_LIST_USAGE,
    )
    parser.add_argument(
        "--unreviewed", action="store_true",
        help="Only field-notes not yet reviewed or archived.",
    )
    parser.add_argument(
        "--project", default=None, help="Filter by project slug or id.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of rows to return.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_FIELD_NOTE_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"category_prefix": _FIELD_NOTE_CATEGORY_PREFIX}
    if parsed.unreviewed:
        payload["unreviewed"] = True
    if parsed.project:
        payload["project"] = parsed.project
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    return dispatch_and_emit(
        function_id="ouroboros.field_note.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


OUROBOROS_FIELD_NOTE_GET_USAGE = (
    "yoke ouroboros field-note get ENTRY_ID [--session-id S] [--json]"
)


def ouroboros_field_note_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros field-note get",
        description=OUROBOROS_FIELD_NOTE_GET_USAGE,
    )
    parser.add_argument("entry_id", help="Field-note entry id (integer).")
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
            "category_prefix": _FIELD_NOTE_CATEGORY_PREFIX,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# ouroboros.field_note.append
# ---------------------------------------------------------------------------

OUROBOROS_USAGE = (
    "yoke ouroboros field-note append "
    "--kind {failed|new|unclear|observation} "
    "(--evidence TEXT | --evidence-file PATH) [--corrects ENTRY_ID] "
    "[--correlation-id ID] [--session-id S] [--json]"
)


def ouroboros_field_note_append(args: List[str]) -> int:
    # --help body is composed in yoke_contracts.field_note_text.HELP_BODY
    # from the worked failure modes, decision tree, canonical vocabulary,
    # and inline-short footer. Sourcing it here keeps drift impossible —
    # the constant is the single source of truth across every consumer.
    # RawDescriptionHelpFormatter preserves the renderer's multi-line layout.
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros field-note append",
        description=HELP_BODY,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--kind", required=True, choices=KIND_VALUES,
        help="Field-note signal — failed, new, unclear, or observation.",
    )
    evidence_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        evidence_group, "--evidence", "--evidence-file",
        dest="evidence",
        help_text=(
            f"Non-empty evidence text (≤{EVIDENCE_MAX_CHARS} chars). "
            "Use --evidence-file to read from a path."
        ),
    )
    parser.add_argument(
        "--corrects", dest="corrects", type=int, default=None,
        help=(
            "Entry id this note corrects. The two are linked and the "
            "corrected note is superseded — it leaves the unreviewed queue "
            "so curate clusters this note instead of both. Use it when you "
            "are restating a note you already filed (wrong evidence, wrong "
            "kind, wrong diagnosis); file a fresh note for unrelated signal."
        ),
    )
    parser.add_argument(
        "--correlation-id", dest="correlation_id", default=None,
        help="Optional correlation id (polish-run id, doctor-run id, etc.).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_USAGE)
    if parsed is None:
        return 2

    try:
        evidence = resolve_text_file(
            parsed.evidence, parsed.evidence_file, "--evidence-file",
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
    # The dispatched-subagent role is only observable here, in the calling
    # process; the write handler runs server-side and cannot see it.
    actor_role = resolve_actor_role()
    if actor_role:
        payload["actor_role"] = actor_role
    return dispatch_and_emit(
        function_id="ouroboros.field_note.append",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )

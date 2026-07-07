"""``yoke ouroboros …`` + ``yoke scratch dispatch-inputs`` adapters.

Covers the function ids whose target shape differs from the items/claims
patterns (the events.* family lives in
:mod:`yoke_cli.commands.adapters.events`):

* ``ouroboros.field_note.append`` — ``yoke ouroboros field-note
  append`` (target.kind ``global``)
* ``ouroboros.field_note.list`` / ``ouroboros.field_note.get`` —
  field-note-only readers over the ouroboros entry table
* ``ouroboros.entry.list`` / ``ouroboros.entry.get`` — curate-loop
  entry readers (target.kind ``global``)
* ``scratch.dispatch_inputs`` — client-local path resolver
"""

from __future__ import annotations

import argparse
import importlib
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    resolve_item_id_via_dispatch,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_contracts.field_note_text import HELP_BODY
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "ouroboros_field_note_append",
    "ouroboros_field_note_list", "ouroboros_field_note_get",
    "ouroboros_entry_list", "ouroboros_entry_get",
    "scratch_dispatch_inputs",
    "OUROBOROS_USAGE",
    "OUROBOROS_FIELD_NOTE_LIST_USAGE", "OUROBOROS_FIELD_NOTE_GET_USAGE",
    "OUROBOROS_ENTRY_LIST_USAGE", "OUROBOROS_ENTRY_GET_USAGE",
    "SCRATCH_DISPATCH_INPUTS_USAGE",
]


# ---------------------------------------------------------------------------
# ouroboros.entry.list / ouroboros.entry.get
# ---------------------------------------------------------------------------

OUROBOROS_ENTRY_LIST_USAGE = (
    "yoke ouroboros entry list [--unreviewed] [--project P] "
    "[--limit N] [--session-id S] [--json]"
)


def ouroboros_entry_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry list",
        description=OUROBOROS_ENTRY_LIST_USAGE,
    )
    parser.add_argument(
        "--unreviewed", action="store_true",
        help="Only entries not yet reviewed or archived.",
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
    parsed = parse_or_usage_error(parser, args, OUROBOROS_ENTRY_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.unreviewed:
        payload["unreviewed"] = True
    if parsed.project:
        payload["project"] = parsed.project
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    return dispatch_and_emit(
        function_id="ouroboros.entry.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


OUROBOROS_ENTRY_GET_USAGE = (
    "yoke ouroboros entry get ENTRY_ID [--session-id S] [--json]"
)


def ouroboros_entry_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry get",
        description=OUROBOROS_ENTRY_GET_USAGE,
    )
    parser.add_argument("entry_id", help="Ouroboros entry id (integer).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_ENTRY_GET_USAGE)
    if parsed is None:
        return 2
    try:
        entry_id = int(parsed.entry_id)
    except ValueError:
        return usage_error("ENTRY_ID must be an integer")
    return dispatch_and_emit(
        function_id="ouroboros.entry.get",
        target=TargetRef(kind="global"),
        payload={"entry_id": entry_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


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
    "(--evidence TEXT | --evidence-file PATH) [--correlation-id ID] "
    "[--session-id S] [--json]"
)


def ouroboros_field_note_append(args: List[str]) -> int:
    handler = importlib.import_module(
        "yoke_core.domain.handlers.ouroboros_field_note"
    )

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
        "--kind", required=True, choices=handler.FIELD_NOTE_KIND_VALUES,
        help="Field-note signal — failed, new, unclear, or observation.",
    )
    evidence_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        evidence_group, "--evidence", "--evidence-file",
        dest="evidence",
        help_text=(
            f"Non-empty evidence text (≤{handler.EVIDENCE_MAX_CHARS} chars). "
            "Use --evidence-file to read from a path."
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
    return dispatch_and_emit(
        function_id="ouroboros.field_note.append",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# scratch.dispatch_inputs
# ---------------------------------------------------------------------------

SCRATCH_DISPATCH_INPUTS_USAGE = (
    "yoke scratch dispatch-inputs <PREFIX-N|item-id> <session_id> <attempt>"
)


def scratch_dispatch_inputs(args: List[str]) -> int:
    """Print the helper-resolved dispatch-inputs absolute path.

    Resolves the path locally via
    :func:`yoke_core.domain.project_scratch_dir.dispatch_inputs_dir`
    (no HTTP roundtrip — the shepherd skill's ``$(...)`` capture is the
    canonical caller and shell-recipe latency would dominate). The
    grammar-rule function id is ``scratch.dispatch_inputs``; the
    matching CLI tokens are ``("scratch", "dispatch-inputs")``.

    Output contract: exactly one line on stdout, the absolute path,
    terminated by a single ``\\n``. Stderr is reserved for errors.
    """

    import sys

    scratch_dir = importlib.import_module(
        "yoke_core.domain.project_scratch_dir"
    )
    parser = argparse.ArgumentParser(
        prog="yoke scratch dispatch-inputs",
        description=SCRATCH_DISPATCH_INPUTS_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("session_id", help="Harness session id.")
    parser.add_argument("attempt", help="Per-dispatch attempt counter (1-based).")
    parsed = parse_or_usage_error(parser, args, SCRATCH_DISPATCH_INPUTS_USAGE)
    if parsed is None:
        return 2

    try:
        item_id = resolve_item_id_via_dispatch(
            parsed.item, parsed.project, parsed.session_id,
        )
    except ValueError as exc:
        return usage_error(str(exc))
    try:
        attempt = int(parsed.attempt)
    except ValueError:
        return usage_error("attempt must be an integer")
    if attempt < 1:
        return usage_error("attempt must be >= 1")
    if not parsed.session_id.strip():
        return usage_error("session_id must be non-empty")

    project = scratch_dir.resolve_active_project()
    path = scratch_dir.dispatch_inputs_dir(project, item_id, parsed.session_id, attempt)
    sys.stdout.write(f"{path}\n")
    sys.stdout.flush()
    return 0

"""Reflection-capture pipeline.

Operator/debug adapter for the structured reflection capture pipeline.
The PostToolUse Agent-tool hook in
:mod:`yoke_core.domain.reflection_capture_hook` is the primary path that
captures subagent reflections in production; this module exposes the
underlying parse + persist pipeline as an in-tree library and as a CLI
operators can run against captured transcript text. The CLI is retained
for ad-hoc backfills and debugging, not as the authoritative capture
surface.

CLI usage::

    python3 -m yoke_core.domain.reflection_capture \\
        --output-text <text-or-path> [--default-agent <agent>] [--project <p>]

Exit codes: 0 success (even if zero entries found), 1 error.
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

from yoke_core.domain.reflection_capture_shape_parsers import ReflectionEntry
from yoke_core.domain.reflection_capture_shapes import CaptureResult, parse_text


# Canonical entry template surfaced inline so the CLI ``--help`` (and
# any caller that imports the constant) renders the expected canonical
# shape without grepping for the regex.
CANONICAL_ENTRY_TEMPLATE = (
    "---REFLECTION-START---\n"
    "---BEGIN ENTRY---\n"
    "timestamp: 2026-05-14T12:00:00Z\n"
    "agent: engineer\n"
    "context: YOK-N task M (optional free-form)\n"
    "category: dispatch-context | path-claim | file-budget | ...\n"
    "<entry body — observation, systemic root cause, improvement>\n"
    "---END ENTRY---\n"
    "(repeat ---BEGIN ENTRY--- ... ---END ENTRY--- per reflection)\n"
    "---REFLECTION-END---"
)


def parse_reflection_blocks(
    text: str, *, default_agent: str = "unknown",
) -> Tuple[List[ReflectionEntry], List[str]]:
    """Parse all reflection entries from *text*.

    Thin wrapper over :func:`reflection_capture_shapes.parse_text` that
    preserves the legacy ``(entries, errors)`` tuple shape existing
    callers depend on. New callers should use ``parse_text`` directly
    to consume the structured :class:`CaptureResult`.
    """
    entries, result = parse_text(text, default_agent=default_agent)
    return entries, list(result.errors)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

EVENT_PERSIST_FAILED = "ReflectionCapturePersistFailed"


def _emit_persist_failed(*, agent: str, category: str, body: str, exc: Exception) -> None:
    """Best-effort emission so silent persist drops become observable."""
    try:
        from yoke_core.domain.events import emit_event
        emit_event(
            EVENT_PERSIST_FAILED,
            event_kind="hook",
            event_type="reflection_capture",
            context={
                "agent": agent,
                "category": category,
                "body_excerpt": body[:200],
                "exception_type": type(exc).__name__,
            },
            session_id=os.environ.get("YOKE_SESSION_ID", ""),
        )
    except Exception:
        pass


def persist_entries(
    entries: List[ReflectionEntry],
    *,
    project: Optional[str] = None,
    _conn=None,
) -> CaptureResult:
    """Persist parsed entries to the ouroboros_entries table.

    Returns a :class:`CaptureResult` summarising what happened.

    *_conn* is for testing only — pass an open connection to skip
    the default ``connect()`` call.
    """
    from yoke_core.domain.ouroboros import cmd_insert_entry

    result = CaptureResult(
        entries_parsed=len(entries),
        entries_persisted=0,
        entries_skipped=0,
        errors=[],
    )

    if _conn is not None:
        conn = _conn
        owns_conn = False
    else:
        from yoke_core.domain.db_helpers import connect
        conn = connect()
        owns_conn = True
    try:
        for entry in entries:
            try:
                ret = cmd_insert_entry(
                    conn,
                    timestamp=entry.timestamp,
                    agent=entry.agent,
                    context=entry.context or None,
                    category=entry.category,
                    body=entry.body,
                    project=project,
                    source="reflection_capture",
                )
                if ret == "Duplicate entry skipped":
                    result.entries_skipped += 1
                else:
                    result.entries_persisted += 1
            except Exception as exc:
                result.errors.append(
                    f"Insert failed for entry (agent={entry.agent}, "
                    f"category={entry.category}): {exc}"
                )
                _emit_persist_failed(
                    agent=entry.agent,
                    category=entry.category,
                    body=entry.body,
                    exc=exc,
                )
    finally:
        if owns_conn:
            conn.close()

    return result


# ---------------------------------------------------------------------------
# Full capture pipeline
# ---------------------------------------------------------------------------

def capture_reflections(
    text: str,
    *,
    default_agent: str = "unknown",
    project: Optional[str] = None,
    _conn=None,
) -> CaptureResult:
    """Parse and persist reflection entries from subagent output.

    Calls :func:`reflection_capture_shapes.parse_text` to get the
    structured block classification and any entries the multi-shape
    parser extracted, then persists those entries via
    :func:`persist_entries`. The returned :class:`CaptureResult` carries
    both the structured block-classification fields (``blocks_seen``,
    ``blocks_unrecognized``, ``unrecognized_block_examples``, ...) and
    the legacy fields (``entries_parsed``, ``entries_persisted``, ...).
    """
    entries, result = parse_text(text, default_agent=default_agent)
    if not entries:
        return result

    persist = persist_entries(entries, project=project, _conn=_conn)
    result.entries_persisted = persist.entries_persisted
    result.entries_duplicate_skipped = persist.entries_skipped
    result.entries_persist_failed = len(persist.errors)
    result.entries_parsed = persist.entries_parsed
    result.entries_skipped = persist.entries_skipped
    result.errors.extend(persist.errors)

    from yoke_core.domain.reflection_capture_field_note import dispatch_markers_for_entry
    session_id = os.environ.get("YOKE_SESSION_ID", "")
    for entry in entries:
        dispatch_markers_for_entry(
            body=entry.body, agent=entry.agent,
            context=entry.context, session_id=session_id,
        )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_HELP_TEXT = (
    "Usage: python3 -m yoke_core.domain.reflection_capture "
    "[--output-text PATH_OR_INLINE] [--default-agent NAME] [--project NAME]\n"
    "\n"
    "Reads a reflection block (REFLECTION-START / REFLECTION-END wrapper "
    "containing one or more BEGIN ENTRY / END ENTRY pairs) from either:\n"
    "  --output-text <path>  — file path; read its contents as the block\n"
    "  --output-text <text>  — inline literal text if it does not name a file\n"
    "  (stdin)               — if --output-text is omitted\n"
    "\n"
    "Each entry inside the block has the canonical shape:\n"
    "\n"
    + CANONICAL_ENTRY_TEMPLATE
    + "\n\n"
    "Persists every well-formed entry to ouroboros_entries; "
    "duplicates are skipped silently; malformed entries print "
    "ERROR lines on stderr and the process exits 1."
)


def _cli_main() -> None:
    """CLI entry point for ``python3 -m yoke_core.domain.reflection_capture``."""
    args = sys.argv[1:]

    if any(a in ("--help", "-h") for a in args):
        print(_HELP_TEXT)
        sys.exit(0)

    output_text: Optional[str] = None
    default_agent = "unknown"
    project: Optional[str] = None

    i = 0
    while i < len(args):
        if args[i] == "--output-text" and i + 1 < len(args):
            val = args[i + 1]
            # If it looks like a file path and exists, read it
            if os.path.isfile(val):
                with open(val, encoding="utf-8") as f:
                    output_text = f.read()
            else:
                output_text = val
            i += 2
        elif args[i] == "--default-agent" and i + 1 < len(args):
            default_agent = args[i + 1]
            i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            sys.exit(2)

    if output_text is None:
        # Read from stdin
        if sys.stdin.isatty():
            print("No --output-text and stdin is a TTY. Nothing to capture.", file=sys.stderr)
            sys.exit(0)
        output_text = sys.stdin.read()

    result = capture_reflections(
        output_text,
        default_agent=default_agent,
        project=project,
    )

    # Output summary
    print(f"parsed={result.entries_parsed} persisted={result.entries_persisted} "
          f"skipped={result.entries_skipped} errors={len(result.errors)}")

    if result.errors:
        for err in result.errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli_main()

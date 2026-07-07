"""``yoke items ...`` + ``yoke lifecycle transition`` flag adapters.

Covers four function ids in the canonical yoke CLI set:

* ``items.get.run`` — ``yoke items get <PREFIX-N> [field ...]``
* ``items.progress_log.append`` — ``yoke items progress-log append``
* ``items.structured_field.replace`` — ``yoke items structured-field replace``
* ``lifecycle.transition.execute`` — ``yoke lifecycle transition``

Each adapter parses its own flags, builds the typed envelope, and
delegates dispatch / response emit to
:mod:`yoke_cli.commands._helpers`.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file


__all__ = [
    "items_get", "items_progress_log_append",
    "items_structured_field_replace", "lifecycle_transition",
    "lifecycle_skip_record_recoverable_substrate",
    "ITEMS_GET_USAGE", "PROGRESS_LOG_USAGE",
    "STRUCTURED_FIELD_USAGE", "LIFECYCLE_TRANSITION_USAGE",
    "LIFECYCLE_SKIP_RECORD_RECOVERABLE_SUBSTRATE_USAGE",
]


# ---------------------------------------------------------------------------
# items.get.run
# ---------------------------------------------------------------------------

ITEMS_GET_USAGE = (
    "yoke items get <PREFIX-N> [field1 field2 ...] "
    "[--section \"## Heading\"] [--session-id S] [--json]"
)


def items_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items get", description=ITEMS_GET_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("fields", nargs="*", help="Optional field projection.")
    parser.add_argument(
        "--section", default=None,
        help=(
            "Print only one '## Heading' block of a structured text or "
            "body field; requires exactly one field argument."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_GET_USAGE)
    if parsed is None:
        return 2
    if parsed.section is not None and len(parsed.fields) != 1:
        got = " ".join(parsed.fields) if parsed.fields else "none"
        return usage_error(
            "--section extracts one '## Heading' block from a single "
            f"field, so it takes exactly one field argument (got "
            f"{len(parsed.fields)}: {got}). Split scalar/full fields and "
            "the section into two calls: read the fields with "
            f"'yoke items get {parsed.item} <fields...>', then the "
            f"section with 'yoke items get {parsed.item} <field> "
            f"--section {parsed.section!r}'."
        )
    requested_fields = list(parsed.fields)
    payload: Dict[str, Any] = {"fields": requested_fields}
    if parsed.section is not None:
        payload["section"] = parsed.section

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        result = response.result or {}
        if parsed.section is not None:
            if not result.get("section_found"):
                print(
                    f"Advisory: section {parsed.section!r} not found on "
                    f"{parsed.item} field {result.get('field')!r}",
                    file=stderr,
                )
                return None
            content = str(result.get("content") or "")
            if content:
                stdout.write(content)
                if not content.endswith("\n"):
                    stdout.write("\n")
            return None
        fields = result.get("fields")
        if requested_fields and isinstance(fields, dict):
            for field in requested_fields:
                value = fields.get(field)
                text = "" if value is None else str(value)
                stdout.write(text)
                if not text.endswith("\n"):
                    stdout.write("\n")
            return None
        print(json.dumps(result, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id="items.get.run",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


# ---------------------------------------------------------------------------
# items.progress_log.append
# ---------------------------------------------------------------------------

PROGRESS_LOG_USAGE = (
    "yoke items progress-log append <PREFIX-N> --headline TEXT "
    "(--content TEXT | --content-file PATH) [--source S] "
    "[--session-id S] [--json]"
)


def items_progress_log_append(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items progress-log append",
        description=PROGRESS_LOG_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--headline", required=True, help="One-line entry headline.")
    content_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        content_group, "--content", "--content-file",
        dest="content",
        help_text="Entry body. Use --content-file to read from a path.",
    )
    parser.add_argument("--source", default=None, help="Optional source tag.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROGRESS_LOG_USAGE)
    if parsed is None:
        return 2
    try:
        content = resolve_text_file(
            parsed.content, parsed.content_file, "--content-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {"headline": parsed.headline, "content": content}
    if parsed.source:
        payload["source"] = parsed.source
    return dispatch_and_emit(
        function_id="items.progress_log.append",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# items.structured_field.replace
# ---------------------------------------------------------------------------

STRUCTURED_FIELD_USAGE = (
    "yoke items structured-field replace <PREFIX-N> --field FIELD "
    "(--content TEXT | --content-file PATH | --stdin) "
    "[--source S] [--force] [--session-id S] [--json]"
)


def items_structured_field_replace(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items structured-field replace",
        description=STRUCTURED_FIELD_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--field", required=True, help="Structured field name.")
    content_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        content_group, "--content", "--content-file",
        dest="content",
        help_text="New field content. Use --content-file to read from a path.",
    )
    content_group.add_argument(
        "--stdin", action="store_true",
        help="Read new field content from stdin.",
    )
    parser.add_argument("--source", default="", help="Optional source tag.")
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass shrinkage / empty guards (use sparingly).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRUCTURED_FIELD_USAGE)
    if parsed is None:
        return 2
    if parsed.stdin:
        content = sys.stdin.read()
    else:
        try:
            content = resolve_text_file(
                parsed.content, parsed.content_file, "--content-file",
            )
        except ValueError as exc:
            return usage_error(str(exc))
    payload: Dict[str, Any] = {
        "field": parsed.field, "content": content,
        "source": parsed.source, "force": bool(parsed.force),
    }
    return dispatch_and_emit(
        function_id="items.structured_field.replace",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# lifecycle.transition.execute
# ---------------------------------------------------------------------------

LIFECYCLE_TRANSITION_USAGE = (
    "yoke lifecycle transition <PREFIX-N> --to STATUS "
    "[--from STATUS] [--reason TEXT] [--session-id S] [--json]"
)


def lifecycle_transition(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke lifecycle transition",
        description=LIFECYCLE_TRANSITION_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--to", dest="to_status", required=True,
                        help="Target lifecycle status.")
    parser.add_argument("--from", dest="from_status", default=None,
                        help="Optional precondition: current status must equal this.")
    parser.add_argument("--reason", default=None, help="Human-readable rationale.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LIFECYCLE_TRANSITION_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"target_status": parsed.to_status}
    if parsed.from_status:
        payload["source_status"] = parsed.from_status
    if parsed.reason:
        payload["reason"] = parsed.reason
    return dispatch_and_emit(
        function_id="lifecycle.transition.execute",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# lifecycle.skip.record_recoverable_substrate
# ---------------------------------------------------------------------------

LIFECYCLE_SKIP_RECORD_RECOVERABLE_SUBSTRATE_USAGE = (
    "yoke lifecycle skip record-recoverable-substrate <PREFIX-N> "
    "--chain-step N --project P --routed-action ACTION "
    "--failure-class CLASS --remediation-owner OWNER "
    "[--current-status STATUS] [--useful-work-began] "
    "[--session-id S] [--json]"
)


def lifecycle_skip_record_recoverable_substrate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke lifecycle skip record-recoverable-substrate",
        description=LIFECYCLE_SKIP_RECORD_RECOVERABLE_SUBSTRATE_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--chain-step", dest="chain_step", type=int, required=True,
                        help="Current /yoke do chain step number.")
    parser.add_argument("--project", required=True,
                        help="Project id the failing handler is bound to.")
    parser.add_argument("--routed-action", dest="routed_action", required=True,
                        help="Routed action that failed (e.g. 'advance').")
    parser.add_argument("--failure-class", dest="failure_class", required=True,
                        help="Structured failure class string.")
    parser.add_argument("--remediation-owner", dest="remediation_owner", required=True,
                        help="Ticket id or recipe owner responsible for the fix.")
    parser.add_argument("--current-status", dest="current_status", default=None,
                        help="Lifecycle status of the failing item at skip time.")
    parser.add_argument("--useful-work-began", dest="useful_work_began",
                        action="store_true", default=False,
                        help="Set when the routed handler made useful progress before the failure.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, LIFECYCLE_SKIP_RECORD_RECOVERABLE_SUBSTRATE_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "chain_step": parsed.chain_step,
        "project": parsed.project,
        "routed_action": parsed.routed_action,
        "failure_class": parsed.failure_class,
        "remediation_owner": parsed.remediation_owner,
        "useful_work_began": parsed.useful_work_began,
    }
    if parsed.current_status:
        payload["current_status"] = parsed.current_status
    return dispatch_and_emit(
        function_id="lifecycle.skip.record_recoverable_substrate",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )

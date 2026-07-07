"""``yoke items section ...`` + ``yoke items structured-field ...`` adapters.

Covers six function ids in one sibling module:

* ``items.section.upsert`` / ``.get`` / ``.delete`` — write/read/remove a
  named ``## heading`` section on an item body via ``target.kind="section"``.
* ``items.structured_field.append_addendum`` — append a fresh
  ``## heading``-led block to a structured field.
* ``items.structured_field.section_upsert`` — upsert a named section
  routed to whichever structured field already carries the heading
  (falls through to ``item_sections`` otherwise).
* ``items.structured_field.section_append`` — append a timestamped
  entry under a named section (the canonical Progress-Log shape).
"""

from __future__ import annotations

import argparse
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
    "items_section_upsert", "items_section_get", "items_section_delete",
    "items_structured_field_append_addendum",
    "items_structured_field_section_upsert",
    "items_structured_field_section_append",
    "ITEMS_SECTION_UPSERT_USAGE", "ITEMS_SECTION_GET_USAGE",
    "ITEMS_SECTION_DELETE_USAGE",
    "STRUCTURED_FIELD_APPEND_ADDENDUM_USAGE",
    "STRUCTURED_FIELD_SECTION_UPSERT_USAGE",
    "STRUCTURED_FIELD_SECTION_APPEND_USAGE",
]


def _resolve_content(parsed: argparse.Namespace, allow_stdin: bool = True) -> str:
    if allow_stdin and getattr(parsed, "stdin", False):
        return sys.stdin.read()
    return resolve_text_file(
        parsed.content, parsed.content_file, "--content-file",
    )


def _add_content_group(parser: argparse.ArgumentParser, *, with_stdin: bool = True) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        group, "--content", "--content-file",
        dest="content",
        help_text="New content. Use --content-file to read from a path.",
    )
    if with_stdin:
        group.add_argument(
            "--stdin", action="store_true",
            help="Read content from stdin.",
        )


# ---------------------------------------------------------------------------
# items.section.upsert / .get / .delete
# ---------------------------------------------------------------------------

ITEMS_SECTION_UPSERT_USAGE = (
    "yoke items section upsert <PREFIX-N> --section NAME "
    "(--content TEXT | --content-file PATH | --stdin) "
    "[--ordering N] [--source S] [--session-id S] [--json]"
)


def items_section_upsert(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items section upsert", description=ITEMS_SECTION_UPSERT_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--section", required=True, help="Section heading (e.g. 'Progress Log').")
    _add_content_group(parser)
    parser.add_argument("--ordering", type=int, default=None,
                        help="Optional section ordering rank.")
    parser.add_argument("--source", default=None, help="Optional source tag.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_SECTION_UPSERT_USAGE)
    if parsed is None:
        return 2
    try:
        content = _resolve_content(parsed)
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {"content": content}
    if parsed.ordering is not None:
        payload["ordering"] = parsed.ordering
    if parsed.source:
        payload["source"] = parsed.source
    return dispatch_and_emit(
        function_id="items.section.upsert",
        target=item_target("section", parsed.item, parsed.project, section_name=parsed.section),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


ITEMS_SECTION_GET_USAGE = (
    "yoke items section get <PREFIX-N> --section NAME [--session-id S] [--json]"
)


def items_section_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items section get", description=ITEMS_SECTION_GET_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--section", required=True, help="Section heading.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_SECTION_GET_USAGE)
    if parsed is None:
        return 2
    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        content = (response.result or {}).get("content", "")
        text = "" if content is None else str(content)
        stdout.write(text)
        if text and not text.endswith("\n"):
            stdout.write("\n")
        return None

    return dispatch_and_emit(
        function_id="items.section.get",
        target=item_target("section", parsed.item, parsed.project, section_name=parsed.section),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


ITEMS_SECTION_DELETE_USAGE = (
    "yoke items section delete <PREFIX-N> --section NAME [--session-id S] [--json]"
)


def items_section_delete(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items section delete", description=ITEMS_SECTION_DELETE_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--section", required=True, help="Section heading to delete.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_SECTION_DELETE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="items.section.delete",
        target=item_target("section", parsed.item, parsed.project, section_name=parsed.section),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# items.structured_field.append_addendum
# ---------------------------------------------------------------------------

STRUCTURED_FIELD_APPEND_ADDENDUM_USAGE = (
    "yoke items structured-field append-addendum <PREFIX-N> --field FIELD "
    "--heading TEXT (--content TEXT | --content-file PATH | --stdin) "
    "[--source S] [--session-id S] [--json]"
)


def items_structured_field_append_addendum(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items structured-field append-addendum",
        description=STRUCTURED_FIELD_APPEND_ADDENDUM_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--field", required=True, help="Structured field name.")
    parser.add_argument("--heading", required=True, help="Addendum '## heading' text.")
    _add_content_group(parser)
    parser.add_argument("--source", default="", help="Optional source tag.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRUCTURED_FIELD_APPEND_ADDENDUM_USAGE)
    if parsed is None:
        return 2
    try:
        content = _resolve_content(parsed)
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {
        "field": parsed.field, "heading": parsed.heading,
        "content": content, "source": parsed.source,
    }
    return dispatch_and_emit(
        function_id="items.structured_field.append_addendum",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# items.structured_field.section_upsert
# ---------------------------------------------------------------------------

STRUCTURED_FIELD_SECTION_UPSERT_USAGE = (
    "yoke items structured-field section-upsert <PREFIX-N> --section TEXT "
    "(--content TEXT | --content-file PATH | --stdin) "
    "[--ordering N] [--source S] [--session-id S] [--json]"
)


def items_structured_field_section_upsert(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items structured-field section-upsert",
        description=STRUCTURED_FIELD_SECTION_UPSERT_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--section", required=True, help="Section heading.")
    _add_content_group(parser)
    parser.add_argument("--ordering", type=int, default=None,
                        help="Optional section ordering rank.")
    parser.add_argument("--source", default=None, help="Optional source tag.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRUCTURED_FIELD_SECTION_UPSERT_USAGE)
    if parsed is None:
        return 2
    try:
        content = _resolve_content(parsed)
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {"section": parsed.section, "content": content}
    if parsed.ordering is not None:
        payload["ordering"] = parsed.ordering
    if parsed.source:
        payload["source"] = parsed.source
    return dispatch_and_emit(
        function_id="items.structured_field.section_upsert",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# items.structured_field.section_append
# ---------------------------------------------------------------------------

STRUCTURED_FIELD_SECTION_APPEND_USAGE = (
    "yoke items structured-field section-append <PREFIX-N> --section TEXT "
    "--headline TEXT (--content TEXT | --content-file PATH | --stdin) "
    "[--ordering N] [--source S] [--session-id S] [--json]"
)


def items_structured_field_section_append(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items structured-field section-append",
        description=STRUCTURED_FIELD_SECTION_APPEND_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--section", required=True, help="Section heading.")
    parser.add_argument("--headline", required=True, help="Entry headline.")
    _add_content_group(parser)
    parser.add_argument("--ordering", type=int, default=None,
                        help="Optional section ordering rank.")
    parser.add_argument("--source", default=None, help="Optional source tag.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRUCTURED_FIELD_SECTION_APPEND_USAGE)
    if parsed is None:
        return 2
    try:
        content = _resolve_content(parsed)
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {
        "section": parsed.section, "headline": parsed.headline, "content": content,
    }
    if parsed.ordering is not None:
        payload["ordering"] = parsed.ordering
    if parsed.source:
        payload["source"] = parsed.source
    return dispatch_and_emit(
        function_id="items.structured_field.section_append",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )

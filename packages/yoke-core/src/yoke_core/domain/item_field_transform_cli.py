"""CLI dispatch for :mod:`yoke_core.domain.item_field_transform`.

Extracted from the main module so each subcommand:

1. Parses CLI args.
2. Resolves stdin / body-file content.
3. Executes the operation. Two paths share one set of inputs:
   - **Human / legacy default** — call the domain helper directly and
     emit the legacy ``TransformResult.to_json()`` line. Backward-compat
     with every operator workflow and every existing test.
   - **``--json`` machine mode** — build a
     :class:`FunctionCallRequest` for the matching
     ``items.structured_field.*`` function id, dispatch via
     :func:`yoke_core.domain.yoke_function_dispatch.dispatch`, and
     emit the typed envelope verbatim. The dispatcher path enforces
     claim verification, idempotency, and event emission.

The duality preserves the legacy contract while exposing the dispatcher
parity. The function dispatcher and ``item_field_transform.append_addendum``
share the same underlying domain helper, so the typed envelope emitted by
``--json`` mode is parity-equivalent to the legacy dataclass evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.structured_field_input import (
    ContentInputError,
    read_body_file_or_raise,
    resolve_content_input,
)
from yoke_core.api.service_client_structured_api_adapter import (
    call_dispatcher,
    emit_response,
)


_APPEND_ADDENDUM = "append-addendum"
_SECTION_UPSERT = "section-upsert"
_SECTION_APPEND = "section-append"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.item_field_transform",
        description=(
            "Safe additive transforms on structured item fields. "
            "Default output is the legacy TransformResult JSON line; "
            "``--json`` routes through the function dispatcher and emits "
            "the FunctionCallResponse envelope verbatim."
        ),
    )
    sub = parser.add_subparsers(dest="operation", required=True)

    addendum = sub.add_parser(
        _APPEND_ADDENDUM,
        help="Append a ## heading-led block to a structured field.",
    )
    addendum.add_argument("--item", required=True)
    addendum.add_argument("--field", required=True)
    addendum.add_argument("--heading", required=True)
    addendum.add_argument("--source", default="")
    addendum.add_argument("--stdin", action="store_true")
    addendum.add_argument("--body-file", dest="body_file", default=None)
    addendum.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Route through the function dispatcher and emit the typed envelope.",
    )

    section = sub.add_parser(
        _SECTION_UPSERT,
        help="Upsert a rendered section; structured-field matches update in-field.",
    )
    section.add_argument("--item", required=True)
    section.add_argument("--section", required=True)
    section.add_argument("--ordering", type=int, default=None)
    section.add_argument("--source", default=None)
    section.add_argument("--stdin", action="store_true")
    section.add_argument("--body-file", dest="body_file", default=None)
    section.add_argument(
        "--json", dest="json_mode", action="store_true",
        help="Route through the function dispatcher and emit the typed envelope.",
    )

    append = sub.add_parser(
        _SECTION_APPEND,
        help="Append a Progress Log-style entry to an item_sections row.",
    )
    append.add_argument("--item", required=True)
    append.add_argument("--section", required=True)
    append.add_argument("--headline", required=True)
    append.add_argument("--ordering", type=int, default=None)
    append.add_argument("--source", default=None)
    append.add_argument("--stdin", action="store_true")
    append.add_argument("--body-file", dest="body_file", default=None)
    append.add_argument(
        "--json", dest="json_mode", action="store_true",
        help="Route through the function dispatcher and emit the typed envelope.",
    )

    return parser


def _resolve_content(args, operation: str) -> tuple[Optional[str], Optional[int]]:
    try:
        content_input = resolve_content_input(
            stdin_flag=getattr(args, "stdin", False),
            body_file=getattr(args, "body_file", None),
        )
        if content_input.mode == "stdin":
            return (content_input.content or "", None)
        return (read_body_file_or_raise(content_input.file_path or ""), None)
    except ContentInputError as exc:
        from yoke_core.domain.item_field_transform import _fail

        print(_fail(operation, exc.message).to_json())
        return (None, exc.exit_code)


def _parse_item_id(raw: str, operation: str) -> tuple[Optional[int], int]:
    from yoke_core.domain.item_field_transform import _fail, parse_item_id

    try:
        return (parse_item_id(raw), 0)
    except ValueError as exc:
        print(_fail(operation, str(exc)).to_json())
        return (None, 1)


def _run_legacy(operation: str, args, content: str, item_id: int) -> int:
    """Execute the domain helper directly and emit the legacy evidence line."""
    from yoke_core.domain.item_field_transform import (
        append_addendum,
        section_append,
        section_upsert,
    )

    if operation == _APPEND_ADDENDUM:
        result = append_addendum(
            item_id=item_id, field=args.field, heading=args.heading,
            content=content, source=args.source,
        )
    elif operation == _SECTION_APPEND:
        result = section_append(
            item_id=item_id, section=args.section, headline=args.headline,
            content=content, ordering=args.ordering, source=args.source,
        )
    else:  # section-upsert
        result = section_upsert(
            item_id=item_id, section=args.section, content=content,
            ordering=args.ordering, source=args.source,
        )

    print(result.to_json())
    return 0 if result.success else 1


def _ensure_handlers_registered() -> None:
    """Register handlers on first ``--json`` use.

    In-process callers reach the dispatcher through the FastAPI lifespan
    that calls :func:`register_all_handlers` once at startup. Standalone
    CLI invocations do not go through that lifespan, so the registry is
    bootstrapped lazily here. The registration helper is idempotent.
    """
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers

    register_all_handlers()


def _dispatch_via_function(operation: str, args, content: str, item_id: int) -> int:
    """Build the matching ``items.structured_field.*`` request and dispatch."""
    _ensure_handlers_registered()

    if operation == _APPEND_ADDENDUM:
        response = call_dispatcher(
            function_id="items.structured_field.append_addendum",
            target=TargetRef(kind="item", item_id=item_id),
            payload={
                "field": args.field,
                "heading": args.heading,
                "content": content,
                "source": args.source or "",
            },
        )
    elif operation == _SECTION_APPEND:
        payload = {
            "section": args.section,
            "headline": args.headline,
            "content": content,
        }
        if args.ordering is not None:
            payload["ordering"] = args.ordering
        if args.source is not None:
            payload["source"] = args.source
        response = call_dispatcher(
            function_id="items.structured_field.section_append",
            target=TargetRef(kind="item", item_id=item_id),
            payload=payload,
        )
    else:  # section-upsert
        payload = {"section": args.section, "content": content}
        if args.ordering is not None:
            payload["ordering"] = args.ordering
        if args.source is not None:
            payload["source"] = args.source
        response = call_dispatcher(
            function_id="items.structured_field.section_upsert",
            target=TargetRef(kind="item", item_id=item_id),
            payload=payload,
        )
    return emit_response(response, json_mode=True)


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    operation = args.operation

    content, exit_code = _resolve_content(args, operation)
    if content is None:
        return exit_code or 1

    item_id, parse_exit = _parse_item_id(args.item, operation)
    if item_id is None:
        return parse_exit

    if bool(args.json_mode):
        return _dispatch_via_function(operation, args, content, item_id)
    return _run_legacy(operation, args, content, item_id)


__all__ = ["main"]

"""Field-aware section-upsert CLI adapter."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.section_upsert_receipt import verify_field_receipt


STRUCTURED_FIELD_SECTION_UPSERT_USAGE = (
    "yoke items structured-field section-upsert <PREFIX-N> --section TEXT "
    "(--content TEXT | --content-file PATH | --stdin) "
    "[--field FIELD [--heading-level 2–6] | --ordering N] [--source S] [--session-id S] [--json]"
)


def items_structured_field_section_upsert(args: List[str]) -> int:
    from yoke_cli.commands.adapters.items_section import (
        _add_content_group,
        _resolve_content,
    )

    parser = argparse.ArgumentParser(
        prog="yoke items structured-field section-upsert",
        description=STRUCTURED_FIELD_SECTION_UPSERT_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N).")
    parser.add_argument("--section", required=True, help="Section heading.")
    _add_content_group(parser)
    parser.add_argument(
        "--field", default=None, help="Target this stored structured field."
    )
    parser.add_argument("--heading-level", type=int, choices=range(2, 7), default=None)
    parser.add_argument(
        "--ordering", type=int, default=None, help="Optional section ordering rank."
    )
    parser.add_argument("--source", default=None, help="Optional source tag.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRUCTURED_FIELD_SECTION_UPSERT_USAGE)
    if parsed is None:
        return 2
    try:
        content = _resolve_content(parsed)
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {"section": parsed.section, "content": content}
    if parsed.field is not None:
        payload["field"] = parsed.field
    if parsed.heading_level is not None:
        payload["heading_level"] = parsed.heading_level
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
        response_recovery=(
            lambda response, _actor: verify_field_receipt(response, parsed.field)
        )
        if parsed.field is not None
        else None,
    )

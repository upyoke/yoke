"""``yoke items scalar update`` flag adapter.

Covers the function id ``items.scalar.update`` — single-field scalar
update with frozen-item rejection. Supported fields are enumerated in
:data:`yoke_core.domain.mutation_fields.SUPPORTED_UPDATE_FIELDS`
(status, frozen, blocked, blocked_reason, priority, project,
deployment_flow, deployed_to, title).

Value handling:

* ``--value VALUE`` — string value. Bool fields (``frozen``, ``blocked``)
  accept ``true|false|1|0`` and are coerced server-side by
  :mod:`yoke_core.domain.backlog`.
* ``--null`` — set the field to null (for nullable fields such as
  ``blocked_reason``).
* ``--value-json JSON`` — typed value parsed as JSON (rare; for
  integers / booleans / structured values when the string form is
  ambiguous).
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)


__all__ = ["items_scalar_update", "ITEMS_SCALAR_UPDATE_USAGE"]


ITEMS_SCALAR_UPDATE_USAGE = (
    "yoke items scalar update PREFIX-N --field FIELD "
    "(--value VALUE | --null | --value-json JSON) "
    "[--done-nonce-verified] [--force] [--qa-bypass] "
    "[--project P] [--session-id S] [--json]"
)


def items_scalar_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items scalar update",
        usage=ITEMS_SCALAR_UPDATE_USAGE,
    )
    parser.add_argument("item", metavar="PREFIX-N", help="The item to change.")
    parser.add_argument(
        "--field",
        required=True,
        metavar="FIELD",
        help=(
            "Field to change: status, frozen, blocked, blocked_reason, priority, "
            "project, deployment_flow, deployed_to or title."
        ),
    )
    value_group = parser.add_mutually_exclusive_group(required=True)
    value_group.add_argument(
        "--value",
        default=None,
        metavar="VALUE",
        help="New value as text. frozen and blocked accept true, false, 1 or 0.",
    )
    value_group.add_argument(
        "--null",
        action="store_true",
        help="Set the field to null (nullable fields only).",
    )
    value_group.add_argument(
        "--value-json",
        dest="value_json",
        default=None,
        metavar="JSON",
        help="New value as JSON, when plain text is ambiguous (numbers, booleans).",
    )
    parser.add_argument(
        "--done-nonce-verified",
        dest="done_nonce_verified",
        action="store_true",
        help="For internal callers only: the caller already checked the done nonce.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Change a frozen item and skip the status gates. Use sparingly.",
    )
    parser.add_argument(
        "--qa-bypass",
        dest="qa_bypass",
        action="store_true",
        help="Skip the QA gates; you assert QA is handled.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_SCALAR_UPDATE_USAGE)
    if parsed is None:
        return 2
    if parsed.value_json is not None:
        try:
            value: Any = json.loads(parsed.value_json)
        except json.JSONDecodeError as exc:
            return usage_error(f"--value-json invalid JSON: {exc}")
    elif parsed.null:
        value = None
    else:
        value = parsed.value
    payload: Dict[str, Any] = {
        "field": parsed.field,
        "value": value,
        "done_nonce_verified": bool(parsed.done_nonce_verified),
        "force": bool(parsed.force),
        "qa_bypass": bool(parsed.qa_bypass),
    }
    return dispatch_and_emit(
        function_id="items.scalar.update",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )

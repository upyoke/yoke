"""Project engine item identities onto the public function response contract.

Handlers retain integer keys for internal joins. The dispatch boundary resolves
the complete result's item set once and removes those keys before returning it.
"""

from __future__ import annotations

import re

from typing import Any, Mapping

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.timestamps import temporal_wire
from yoke_contracts.public_item_contract import (
    is_engine_protocol_field,
    is_public_item_record,
    item_record_context,
)
from yoke_contracts.item_identity_keys import wire_key_for_engine
from yoke_core.domain.item_ref_render import ItemRefLookup, render_item_refs


# Error messages are engine-written, so an item number named in one is a join
# key. Result strings are never scanned: they carry stored user prose, which
# must round-trip unchanged. Requirement numbers, run ids and existing PREFIX-N
# references retain their domain meaning.
_ITEM_TEXT_RE = re.compile(
    r"(?<![\w.-])(?:items\.id|(?:deployment[ \t]+)?(?:item|epic|member)s?)"
    r"[ \t]+[\"']?(?P<item_id>[0-9]+)(?![\w-])",
    re.IGNORECASE,
)


def _error_ids(message: str) -> set[int]:
    return {int(match["item_id"]) for match in _ITEM_TEXT_RE.finditer(message)}


def _public_error_text(message: str, refs: ItemRefLookup) -> str:
    def replace(match: re.Match[str]) -> str:
        start, end = match.span("item_id")
        return (
            match[0][: start - match.start()]
            + refs(match["item_id"])
            + match[0][end - match.start() :]
        )

    return _ITEM_TEXT_RE.sub(replace, message)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int) or isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def collect_item_ids(node: Any, *, item_context: bool = False) -> set[int]:
    ids: set[int] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if is_engine_protocol_field(key):
                continue
            identity = wire_key_for_engine(key)
            if (
                identity
                or key == "internal_id"
                or key == "id"
                and is_public_item_record(node, context=item_context)
            ):
                values = value if isinstance(value, list) else [value]
                ids.update(
                    number for v in values if (number := _integer(v)) is not None
                )
            ids.update(collect_item_ids(value, item_context=item_record_context(key)))
    elif isinstance(node, list):
        for value in node:
            ids.update(collect_item_ids(value, item_context=item_context))
    return ids


def public_result(node: Any, refs: Mapping[int, str]) -> Any:
    from yoke_contracts.public_item_contract import project_public_identities

    return project_public_identities(node, ItemRefLookup(dict(refs)))


def public_response(response: FunctionCallResponse) -> FunctionCallResponse:
    # Pack bundles own content-addressed application source; projecting any
    # identity inside them invalidates the file digest.
    if response.success and response.function in {"packs.bundle.get", "packs.bundle.render"}:
        return response.model_copy(update={"result": temporal_wire(response.result)})
    error_message = response.error.message if response.error else ""
    ids = collect_item_ids(response.result) | _error_ids(error_message)
    refs: dict[int, str] = {}
    if ids:
        from yoke_core.domain.db_helpers import connect

        try:
            with connect() as conn:
                refs = render_item_refs(conn, sorted(ids))
        except Exception as exc:
            return response.model_copy(
                update={
                    "success": False,
                    "result": None,
                    "error": FunctionError(
                        code="public_response_identity_unavailable",
                        message=f"Cannot compose public item identities: {exc}",
                        recovery_hint="Check the control-plane connection with `yoke env list`, then retry.",
                    ),
                }
            )
    lookup = ItemRefLookup(refs)
    update = {
        "result": temporal_wire(public_result(response.result, refs))
    }
    if response.error:
        update["error"] = response.error.model_copy(
            update={"message": _public_error_text(error_message, lookup)}
        )
    return response.model_copy(update=update)

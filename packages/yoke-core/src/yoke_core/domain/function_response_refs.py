"""Project engine item identities onto the public function response contract.

Handlers retain integer keys for internal joins. The dispatch boundary resolves
the complete result's item set once and removes those keys before returning it.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.public_item_contract import (
    is_engine_protocol_field,
    is_public_item_record,
    item_record_context,
)
from yoke_contracts.item_identity_keys import wire_key_for_engine
from yoke_core.domain.item_ref_render import ItemRefLookup, render_item_refs


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
    if response.result is None:
        return response
    ids = collect_item_ids(response.result)
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
    return response.model_copy(update={"result": public_result(response.result, refs)})

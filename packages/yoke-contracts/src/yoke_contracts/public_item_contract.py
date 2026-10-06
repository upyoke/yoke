"""Public item identity at client and HTTP boundaries."""

from __future__ import annotations

from typing import Any, Callable

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionError
from yoke_contracts.item_identity_keys import engine_key_for_wire, wire_key_for_engine
from yoke_contracts.public_ref import parse_public_item_ref


def _public(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    prefix, sequence = parse_public_item_ref(value)
    return prefix is not None and sequence is not None


def public_item_request_error(request: FunctionCallRequest) -> FunctionError | None:
    """Refuse internal join keys before a client sends or HTTP dispatches them."""
    target = request.target
    if target.item_id is not None or target.epic_id is not None:
        return FunctionError(
            code="internal_item_id_forbidden",
            message="Internal item ids are engine join keys; send target.public_ref (PREFIX-N) alone.",
            jsonpath="$.target",
        )
    if target.public_ref is not None and not _public(target.public_ref):
        return FunctionError(
            code="public_item_ref_required",
            message="Send the complete public item ref (PREFIX-N); bare numbers are not client identities.",
            jsonpath="$.target.public_ref",
        )

    def inspect(node: Any, path: str) -> FunctionError | None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                error = inspect(child, f"{path}[{index}]")
                if error:
                    return error
        if not isinstance(node, dict):
            return None
        for key, child in node.items():
            wire = wire_key_for_engine(key)
            if wire or key == "internal_id":
                return FunctionError(
                    code="internal_item_id_forbidden",
                    message=f"{path}.{key} is an internal join key; send {wire or 'public_ref'} (PREFIX-N) instead.",
                    jsonpath=f"{path}.{key}",
                )
            if engine_key_for_wire(key) and child is not None:
                values = child if isinstance(child, list) else [child]
                if any(not _public(value) for value in values):
                    return FunctionError(
                        code="public_item_ref_required",
                        message=f"{path}.{key} must name complete public item refs (PREFIX-N).",
                        jsonpath=f"{path}.{key}",
                    )
            error = inspect(child, f"{path}.{key}")
            if error:
                return error
        return None

    return inspect(request.payload, "$.payload")


def item_record_context(key: str) -> bool:
    """Item containers identify sparse item records without inferring from a ref."""
    return key in ("item", "items") or key.endswith("_items")


def is_public_item_record(node: dict[str, Any], *, context: bool = False) -> bool:
    """Separate an item row from another record that merely names an item."""
    if any(
        key in node
        for key in (
            "method_id",
            "qa_kind",
            "requirement_id",
            "qa_requirement_id",
            "claim_id",
            "worker",
            "caveat_num",
            "artifact_type",
            "task_num",
        )
    ):
        return False
    named = any(_public(node.get(key)) for key in ("public_ref", "item_ref", "ref"))
    return (
        context
        or named
        and any(
            key in node
            for key in (
                "title",
                "workflow_id",
                "project_sequence",
            )
        )
    )


def project_public_identities(
    node: Any,
    render_id: Callable[[int], Any],
    *,
    item_context: bool = False,
) -> Any:
    """Copy a result, rendering join keys and retaining other record ids.

    The engine supplies its bulk-resolved renderer. A client reading an older
    serving build supplies a renderer returning ``None`` and drops identities
    that build did not compose, while retaining any existing public siblings.
    """

    def render(value: Any) -> Any:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int) or isinstance(value, str) and value.isdigit():
            return render_id(int(value))
        return value

    if isinstance(node, list):
        return [
            project_public_identities(child, render_id, item_context=item_context)
            for child in node
        ]
    if not isinstance(node, dict):
        return node
    item_row = is_public_item_record(node, context=item_context)
    out = {}
    for key, value in node.items():
        wire = wire_key_for_engine(key)
        if (
            key == "internal_id"
            or key == "id"
            and item_row
            and (isinstance(value, int) or isinstance(value, str) and value.isdigit())
        ):
            if not node.get("public_ref"):
                ref = render(value)
                if ref is not None:
                    out["public_ref"] = ref
            continue
        if wire:
            if wire not in node:
                ref = (
                    [render(v) for v in value]
                    if isinstance(value, list)
                    else render(value)
                )
                if ref is not None:
                    out[wire] = ref
            continue
        out[key] = project_public_identities(
            value, render_id, item_context=item_record_context(key)
        )
    return out


def public_payload_schema(node: Any) -> Any:
    """Describe wire identities while engine models retain their join keys."""
    if isinstance(node, list):
        return [public_payload_schema(child) for child in node]
    if not isinstance(node, dict):
        return node
    out = {key: public_payload_schema(value) for key, value in node.items()}
    properties = out.get("properties")
    if not isinstance(properties, dict):
        return out
    renamed = {}
    for key, schema in properties.items():
        wire = wire_key_for_engine(key)
        if wire is None:
            renamed[key] = schema
            continue
        ref_schema = {"type": "string", "description": "Public item ref (PREFIX-N)."}
        plural = key.endswith("_ids")
        identity = {"type": "array", "items": ref_schema} if plural else ref_schema
        nullable = any(part.get("type") == "null" for part in schema.get("anyOf", []))
        if nullable:
            identity = {"anyOf": [identity, {"type": "null"}], "default": None}
        renamed[wire] = identity
    out["properties"] = renamed
    if "required" in out:
        out["required"] = [wire_key_for_engine(key) or key for key in out["required"]]
    return out

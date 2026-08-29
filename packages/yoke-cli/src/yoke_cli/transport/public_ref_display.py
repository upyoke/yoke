"""CLI print-layer translation from internal item ids to public refs.

Human CLI output must never show a bare ``items.id`` integer. ``--json``
keeps the machine payload untouched so validated contracts never gain a
sibling field. This module walks a display copy only.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Mapping, TextIO

from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef


LOOKUP_FUNCTION_ID = "items.public_ref.lookup"
ID_KEYS = ("item_id", "current_item_id", "recent_item_id", "epic_id")
DISPLAY_KEYS = {
    "item_id": "public_ref",
    "current_item_id": "current_public_ref",
    "recent_item_id": "recent_public_ref",
    "epic_id": "epic_public_ref",
}
_MAX_DEPTH = 32
_MAX_LOOKUP_IDS = 512


def coerce_internal_item_id(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if text.isdigit():
            value = int(text)
            return value if value > 0 else None
    return None


def collect_internal_item_ids(node: Any) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    _collect(node, ordered, seen, 0)
    return ordered


def apply_public_refs(node: Any, refs: Mapping[int, str]) -> Any:
    return _apply(node, refs, 0)


def prepare_human_response(response: FunctionCallResponse) -> FunctionCallResponse:
    """Return a copy whose human-visible ids are public refs, or ``response``."""
    if not response.success or not response.result:
        return response
    if response.function == LOOKUP_FUNCTION_ID:
        return response
    ids = collect_internal_item_ids(response.result)
    if not ids:
        return response
    refs = lookup_public_refs(ids)
    display = apply_public_refs(response.result, refs)
    return response.model_copy(update={"result": display})


def lookup_public_refs(item_ids: list[int]) -> dict[int, str]:
    """Resolve internal ids through the registered lookup. Empty on failure."""
    wanted = list(dict.fromkeys(item_ids))[:_MAX_LOOKUP_IDS]
    if not wanted:
        return {}
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

    response = call_dispatcher(
        function_id=LOOKUP_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={"item_ids": wanted},
        actor=build_actor(),
    )
    if not response.success:
        return {}
    raw = (response.result or {}).get("refs") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, str] = {}
    for key, value in raw.items():
        item_id = coerce_internal_item_id(key)
        if item_id is None or not value:
            continue
        out[item_id] = str(value)
    return out


def emit_response(
    response: FunctionCallResponse,
    *,
    json_mode: bool,
    human_writer=None,
) -> int:
    from yoke_cli.transport.dispatcher import response_to_dict

    if json_mode:
        print(json.dumps(response_to_dict(response), sort_keys=True))
    else:
        display = prepare_human_response(response)
        if human_writer is not None and display.success:
            human_writer(display, sys.stdout, sys.stderr)
        else:
            _default_human_writer(display, sys.stdout, sys.stderr)
    return 0 if response.success else 1


def _collect(node: Any, ordered: list[int], seen: set[int], depth: int) -> None:
    if depth > _MAX_DEPTH:
        return
    if isinstance(node, dict):
        for key in ID_KEYS:
            item_id = coerce_internal_item_id(node.get(key))
            if item_id is not None and item_id not in seen:
                seen.add(item_id)
                ordered.append(item_id)
        for value in node.values():
            _collect(value, ordered, seen, depth + 1)
        return
    if isinstance(node, list):
        for item in node:
            _collect(item, ordered, seen, depth + 1)


def _apply(node: Any, refs: Mapping[int, str], depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return node
    if isinstance(node, dict):
        out = {key: _apply(value, refs, depth + 1) for key, value in node.items()}
        if coerce_internal_item_id(out.get("internal_id")) is not None:
            del out["internal_id"]
        for key in ID_KEYS:
            item_id = coerce_internal_item_id(out.get(key))
            if item_id is None:
                continue
            dest = DISPLAY_KEYS[key]
            rendered = refs.get(item_id)
            if not out.get(dest) and rendered:
                out[dest] = rendered
            del out[key]
        return out
    if isinstance(node, list):
        return [_apply(item, refs, depth + 1) for item in node]
    return node


def _default_human_writer(
    response: FunctionCallResponse, stdout: TextIO, stderr: TextIO
) -> None:
    if response.success:
        print(json.dumps(response.result, sort_keys=True), file=stdout)
        for warning in response.warnings:
            print(
                f"warning: {warning.code} ({warning.step}): {warning.detail}",
                file=stderr,
            )
        return
    if response.error is not None:
        print(f"error ({response.error.code}): {response.error.message}", file=stderr)
        if response.error.recovery_hint:
            print(f"hint: {response.error.recovery_hint}", file=stderr)
    else:
        print("error: dispatch returned success=False", file=stderr)


__all__ = [
    "DISPLAY_KEYS",
    "ID_KEYS",
    "LOOKUP_FUNCTION_ID",
    "apply_public_refs",
    "coerce_internal_item_id",
    "collect_internal_item_ids",
    "emit_response",
    "lookup_public_refs",
    "prepare_human_response",
]

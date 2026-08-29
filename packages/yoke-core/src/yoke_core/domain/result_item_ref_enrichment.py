"""Shared outbound enrichment: pair bare ``item_id`` with ``item_ref``.

Agent-facing function-call results historically returned the internal
``items.id`` alone. When that number drifts from the public
``{prefix}-{project_sequence}`` ref, callers treat the envelope as naming
the wrong item. ``items.create`` already returns both fields; this module
extends that convention at the dispatcher envelope layer so handlers do
not assemble refs themselves.

DB rows, events, telemetry, and test assertions keep bare integer
``item_id`` — only the result envelope is enriched.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

from yoke_contracts.opaque_contract_payload import OpaqueContractPayload

# Mapped result keys whose integer (or numeric-string) value is an
# internal items.id and should gain a sibling public-ref field wherever
# they appear. ``epic_id`` is the same identifier (the epic's items.id);
# process/steering scopes carry no item id and are left alone.
_ID_TO_REF_KEYS: tuple[tuple[str, str], ...] = (
    ("item_id", "item_ref"),
    ("current_item_id", "current_item_ref"),
    ("recent_item_id", "recent_item_ref"),
    ("epic_id", "epic_ref"),
)

# Result envelopes are JSON-like; this caps descent so a self-referential
# or hostile payload cannot run unbounded.
_MAX_NESTING_DEPTH = 32

RefLookup = Callable[[int], str]


def _coerce_internal_item_id(raw: Any) -> Optional[int]:
    """Return an internal id when ``raw`` is clearly numeric; else None.

    String public refs (``YOK-2008``) and other non-numeric tokens are left
    alone — those surfaces already carry display identity.
    """
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


def _collect_ids(
    node: Any,
    collected: list[int],
    seen_values: set[int],
    seen_nodes: set[int],
    depth: int,
) -> None:
    if depth > _MAX_NESTING_DEPTH:
        return
    if isinstance(node, OpaqueContractPayload):
        return
    if isinstance(node, dict):
        node_id = id(node)
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        for id_key, ref_key in _ID_TO_REF_KEYS:
            if ref_key in node and node.get(ref_key):
                continue
            item_id = _coerce_internal_item_id(node.get(id_key))
            if item_id is None or item_id in seen_values:
                continue
            seen_values.add(item_id)
            collected.append(item_id)
        for value in node.values():
            _collect_ids(value, collected, seen_values, seen_nodes, depth + 1)
        seen_nodes.discard(node_id)
        return
    if isinstance(node, list):
        node_id = id(node)
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        for item in node:
            _collect_ids(item, collected, seen_values, seen_nodes, depth + 1)
        seen_nodes.discard(node_id)


def _enrich_mapping(payload: MutableMapping[str, Any], lookup: RefLookup) -> None:
    for id_key, ref_key in _ID_TO_REF_KEYS:
        if ref_key in payload and payload.get(ref_key):
            continue
        item_id = _coerce_internal_item_id(payload.get(id_key))
        if item_id is None:
            continue
        rendered = lookup(item_id)
        if rendered:
            payload[ref_key] = rendered


def _apply(
    node: Any,
    lookup: RefLookup | None,
    seen_nodes: set[int],
    depth: int,
) -> Any:
    if isinstance(node, OpaqueContractPayload):
        return dict(node)
    if isinstance(node, dict):
        if depth > _MAX_NESTING_DEPTH or id(node) in seen_nodes:
            return dict(node)
        seen_nodes.add(id(node))
        out = {
            key: _apply(value, lookup, seen_nodes, depth + 1)
            for key, value in node.items()
        }
        if lookup is not None:
            _enrich_mapping(out, lookup)
        seen_nodes.discard(id(node))
        return out
    if isinstance(node, list):
        if depth > _MAX_NESTING_DEPTH or id(node) in seen_nodes:
            return list(node)
        seen_nodes.add(id(node))
        out = [_apply(item, lookup, seen_nodes, depth + 1) for item in node]
        seen_nodes.discard(id(node))
        return out
    return node


def enrich_result_item_refs(
    result: Mapping[str, Any] | None,
    *,
    conn: Any = None,
) -> dict[str, Any]:
    """Return a copy of ``result`` with public refs beside bare ids.

    Walks nested display objects and arrays so a mapped key gains its sibling
    ref wherever it appears. Exact-shape contract payloads are copied without
    enrichment. Distinct ids are resolved in one statement.
    Opens a short-lived control-plane connection when ``conn`` is omitted.
    On connection or lookup failure the original fields are preserved
    unchanged — never invent a wrong ref.
    """
    if not result:
        return {}
    out: dict[str, Any] = dict(result)

    owns_conn = False
    active = conn
    if active is None:
        try:
            from yoke_contracts.control_plane_locality import (
                RemoteControlPlaneConnectionError,
            )
            from yoke_core.domain import db_helpers

            active = db_helpers.connect()
            owns_conn = True
        except RemoteControlPlaneConnectionError:
            # Outside Exception on purpose — https authority has no local DB.
            return out
        except Exception:
            return out
    try:
        collected: list[int] = []
        _collect_ids(result, collected, set(), set(), 0)
        lookup: RefLookup | None = None
        if collected:
            from yoke_core.domain.item_ref_render import render_item_ref_lookup

            lookup = render_item_ref_lookup(active, collected)
        walked = _apply(result, lookup, set(), 0)
        return walked if isinstance(walked, dict) else out
    except Exception:
        return out
    finally:
        if owns_conn and active is not None:
            try:
                active.close()
            except Exception:
                pass

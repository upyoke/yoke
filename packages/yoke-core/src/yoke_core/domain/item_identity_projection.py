"""Project internal item ids in a function response onto public refs.

Handlers answer in engine terms — ``item_id``, ``epic_id``,
``<role>_item_id`` and their plural lists. At the dispatcher boundary every
such id gains its wire counterpart (:mod:`item_identity_keys`): the public
ref under the paired ``public_ref``-family key, rendered for the whole
response in one statement. A wire key the handler already filled is kept.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from yoke_core.domain.item_identity_keys import is_plural, wire_key_for_engine

_MAX_DEPTH = 32


def _as_item_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def _engine_ids(key: str, value: Any) -> List[int]:
    if wire_key_for_engine(key) is None:
        return []
    if is_plural(key):
        if not isinstance(value, list):
            return []
        return [n for n in (_as_item_id(v) for v in value) if n is not None]
    item_id = _as_item_id(value)
    return [] if item_id is None else [item_id]


def collect_item_ids(node: Any, depth: int = 0) -> List[int]:
    """Every internal item id the response carries under an engine key."""
    found: List[int] = []
    if depth > _MAX_DEPTH:
        return found
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(_engine_ids(str(key), value))
            found.extend(collect_item_ids(value, depth + 1))
    elif isinstance(node, list):
        for value in node:
            found.extend(collect_item_ids(value, depth + 1))
    return found


def apply_public_refs(node: Any, refs: Dict[int, str], depth: int = 0) -> Any:
    """Return ``node`` with each engine id's wire ref filled beside it."""
    if depth > _MAX_DEPTH:
        return node
    if isinstance(node, list):
        return [apply_public_refs(value, refs, depth + 1) for value in node]
    if not isinstance(node, dict):
        return node
    out = {
        key: apply_public_refs(value, refs, depth + 1) for key, value in node.items()
    }
    for key, value in node.items():
        wire_key = wire_key_for_engine(str(key))
        if wire_key is None or out.get(wire_key) is not None:
            continue
        ids = _engine_ids(str(key), value)
        if is_plural(str(key)):
            if isinstance(value, list):
                out[wire_key] = [refs[n] for n in ids if n in refs]
        elif ids and ids[0] in refs:
            out[wire_key] = refs[ids[0]]
    return out


def project_item_identity(conn: Any, result: Any) -> Any:
    """Fill public refs beside every internal item id in ``result``."""
    ids = collect_item_ids(result)
    if not ids:
        return result
    from yoke_core.domain.item_ref_render import render_item_refs

    return apply_public_refs(result, render_item_refs(conn, _unique(ids)))


def _unique(ids: Iterable[int]) -> List[int]:
    return list(dict.fromkeys(ids))


__all__ = ["apply_public_refs", "collect_item_ids", "project_item_identity"]

"""The wire/engine key pairing for item identity in function payloads.

A caller names an item by public ref under a ``public_ref``-family key; the
engine works with the internal ``items.id`` under the matching
``item_id``-family key, onto which the dispatcher resolves it:

* ``public_ref`` <-> ``item_id``; ``<role>_public_ref`` <-> ``<role>_item_id``
* ``epic_public_ref`` <-> ``epic_id``
* the plural ``public_refs`` / ``item_ids`` forms pair the same way.
"""

from __future__ import annotations

from typing import Optional

_SPECIAL_WIRE_TO_ENGINE = {
    "epic_public_ref": "epic_id",
    "epic_public_refs": "epic_ids",
}


def engine_key_for_wire(key: str) -> Optional[str]:
    """The engine key a wire ref key resolves onto, or ``None``."""
    if not isinstance(key, str) or not key.isidentifier():
        return None
    if key in _SPECIAL_WIRE_TO_ENGINE:
        return _SPECIAL_WIRE_TO_ENGINE[key]
    for wire, engine in (("public_refs", "item_ids"), ("public_ref", "item_id")):
        if key == wire:
            return engine
        if key.endswith("_" + wire):
            return key[: -len(wire)] + engine
    return None


def is_plural(key: str) -> bool:
    return (
        isinstance(key, str)
        and key.isidentifier()
        and (key.endswith("public_refs") or key.endswith("_ids"))
    )


def wire_key_for_engine(key: str) -> Optional[str]:
    """Public response key for an internal item join key, or ``None``."""
    if not isinstance(key, str) or not key.isidentifier():
        return None
    for wire, engine in _SPECIAL_WIRE_TO_ENGINE.items():
        if key == engine:
            return wire
    for engine, wire in (("item_ids", "public_refs"), ("item_id", "public_ref")):
        if key == engine:
            return wire
        if key.endswith("_" + engine):
            return key[: -len(engine)] + wire
    return None


__all__ = ["engine_key_for_wire", "is_plural", "wire_key_for_engine"]

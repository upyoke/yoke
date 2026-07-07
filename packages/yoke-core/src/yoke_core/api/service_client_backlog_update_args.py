"""Argument normalization for the public ``items update`` CLI surface.

The legacy positional shape ``items update <id> <field> <value>`` stays
canonical for agent docs. Operators kept reaching for the sibling
adapter convention ``--field``/``--value``, so this helper normalizes
the three named-flag variants into the positional form the existing
dispatcher already handles:

* ``--id <id> --field <field> --value <value>`` → ``<id> <field> <value>``
* ``<id> --field <field> --value <value>``      → ``<id> <field> <value>``
* ``--id <id> <structured-field> --stdin``       → ``<id> <structured-field> --stdin``

Pure normalization — never validates the resulting field/value
combination. Done-nonce, raw-body deny, structured-write dispatch, and
GitHub/board side effects all run unchanged downstream.
"""

from __future__ import annotations

from typing import List


NAMED_FLAGS = ("--id", "--field", "--value")


def has_named_update_flags(args: List[str]) -> bool:
    """True when ``args`` contains any of ``--id``/``--field``/``--value``."""
    return any(a in NAMED_FLAGS for a in args)


def normalize_update_args(args: List[str]) -> List[str]:
    """Translate named ``--id``/``--field``/``--value`` flags into positional.

    Returns a new list. When no named flags are present, returns a copy
    of the input unchanged.

    The named flag set is consumed as a unit: each name captures the
    token immediately after it. If a name appears at the tail with no
    following value, it is passed through to the caller untouched so the
    caller's existing usage-error path can surface the malformed input.
    """
    if not has_named_update_flags(args):
        return list(args)

    named_id: str | None = None
    named_field: str | None = None
    named_value: str | None = None
    rest: List[str] = []

    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--id" and i + 1 < len(args):
            named_id = args[i + 1]
            i += 2
        elif tok == "--field" and i + 1 < len(args):
            named_field = args[i + 1]
            i += 2
        elif tok == "--value" and i + 1 < len(args):
            named_value = args[i + 1]
            i += 2
        else:
            rest.append(tok)
            i += 1

    result: List[str] = []
    if named_id is not None:
        result.append(named_id)
    elif rest:
        # Take the first positional as the item id — mirrors the legacy shape.
        result.append(rest.pop(0))

    if named_field is not None:
        result.append(named_field)
    if named_value is not None:
        result.append(named_value)

    result.extend(rest)
    return result


__all__ = [
    "NAMED_FLAGS",
    "has_named_update_flags",
    "normalize_update_args",
]

"""Internal-id resolution for item tokens crossing the scheduler boundary.

The scheduler's internal currency is the bare ``items.id`` integer. Two
input shapes still arrive from outside that currency:

* ``item_dependencies`` rows store public text refs
  (``{projects.public_item_prefix}-{items.project_sequence}``, e.g.
  ``YOK-1907``) whose sequence may diverge from the internal id.
* Offer/dispatch surfaces receive operator- or payload-supplied item
  tokens that may be an internal int, a bare digit string, or a public
  ``PREFIX-N`` ref.

Both resolvers here translate those tokens to internal ids canonically
(prefix + project_sequence lookup) and fall back to the numeric tail
only when the canonical lookup cannot answer — a missing ``projects``
schema on minimal fixtures, or a ref with no matching item row. The
fallback preserves behavior for refs that never had a backing row while
divergent-sequence items resolve to the correct internal id.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from . import db_backend

_PUBLIC_REF_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-(\d+)$")


def _numeric_tail(text: str) -> Optional[int]:
    match = _PUBLIC_REF_RE.match(text)
    if match:
        return int(match.group(2).lstrip("0") or "0")
    return None


def _rollback_if_postgres(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        try:
            conn.rollback()
        except Exception:
            pass


def resolve_internal_item_id(conn: Any, value: Any) -> Optional[int]:
    """Resolve an item token to the internal ``items.id``, or ``None``.

    Accepts internal ints, bare digit strings (treated as internal ids —
    this is an internal surface, not operator input), and public
    ``PREFIX-N`` refs (resolved via prefix + project_sequence, with a
    numeric-tail fallback when the lookup cannot answer).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text.lstrip("0") or "0")
    match = _PUBLIC_REF_RE.match(text)
    if not match:
        return None
    resolved = internal_ids_for_refs(conn, [text])
    return resolved.get(text)


def internal_ids_for_refs(
    conn: Any, refs: Iterable[str],
) -> Dict[str, int]:
    """Bulk-map public ``PREFIX-N`` refs to internal ``items.id`` values.

    One query resolves every ref via ``projects.public_item_prefix`` +
    ``items.project_sequence``. Refs the canonical lookup cannot answer
    (missing schema, no matching row) fall back to their numeric tail so
    fixture-era refs without backing rows keep their prior meaning.
    Unparseable tokens are omitted from the result.
    """
    wanted: Dict[str, tuple[str, int]] = {}
    result: Dict[str, int] = {}
    for ref in refs:
        text = str(ref).strip()
        match = _PUBLIC_REF_RE.match(text)
        if match:
            wanted[text] = (match.group(1).upper(), int(match.group(2).lstrip("0") or "0"))
        elif text.isdigit():
            result[text] = int(text.lstrip("0") or "0")
    if not wanted:
        return result

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    pairs = sorted(set(wanted.values()))
    prefix_ph = ", ".join(p for _ in pairs)
    seq_ph = ", ".join(p for _ in pairs)
    resolved_pairs: Dict[tuple[str, int], int] = {}
    try:
        rows = conn.execute(
            "SELECT UPPER(p.public_item_prefix) AS prefix, "
            "i.project_sequence AS seq, i.id AS internal_id "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE UPPER(p.public_item_prefix) IN ({prefix_ph}) "
            f"AND i.project_sequence IN ({seq_ph})",
            (*[pr for pr, _ in pairs], *[sq for _, sq in pairs]),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        _rollback_if_postgres(conn)
        rows = []
    for row in rows:
        record = dict(row) if hasattr(row, "keys") else {
            "prefix": row[0], "seq": row[1], "internal_id": row[2],
        }
        if record["seq"] is None:
            continue
        resolved_pairs[(str(record["prefix"]), int(record["seq"]))] = int(
            record["internal_id"]
        )

    for text, pair in wanted.items():
        internal = resolved_pairs.get(pair)
        if internal is None:
            fallback = _numeric_tail(text)
            if fallback is None:
                continue
            internal = fallback
        result[text] = internal
    return result


def remap_ref_keys_to_internal(
    conn: Any, mapping: Dict[str, Any],
) -> Dict[int, Any]:
    """Rekey a public-ref-keyed mapping by internal item id."""
    ref_ids = internal_ids_for_refs(conn, mapping.keys())
    return {
        ref_ids[ref]: value
        for ref, value in mapping.items()
        if ref in ref_ids
    }


__all__ = [
    "internal_ids_for_refs",
    "remap_ref_keys_to_internal",
    "resolve_internal_item_id",
]

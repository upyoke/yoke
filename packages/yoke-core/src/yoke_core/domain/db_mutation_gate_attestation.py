"""Attestation freezing helpers for the joint-gate transition.

Owns :func:`stamp_attestation_frozen_at` and
:func:`clear_attestation_frozen_at` — the canonical mutators called when
the joint gate passes (stamp) and when refining-idea reopens for repair
(clear).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers
from yoke_core.domain.db_compatibility_attestation import FREEZE_FIELD
from yoke_core.domain.db_mutation_gate_shared import (
    _now_iso,
    _safe_parse_dict,
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def stamp_attestation_frozen_at(
    item_id: int,
    *,
    conn: Optional[Any] = None,
    extra_escalations: Optional[Sequence[Mapping[str, object]]] = None,
) -> str:
    """Stamp ``db_compatibility_attestation.frozen_at``.

    Idempotent — re-stamping does not move ``frozen_at`` once set.
    Returns the canonical timestamp written.  When *extra_escalations*
    is supplied the entries are appended to ``class_escalations``.
    """
    from yoke_core.domain import db_compatibility_attestation as dca

    def _stamp(c: Any) -> str:
        p = _placeholder(c)
        row = c.execute(
            f"SELECT db_compatibility_attestation FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Item YOK-{item_id} not found")
        raw = row["db_compatibility_attestation"] if hasattr(row, "keys") else row[0]
        attestation = _safe_parse_dict(raw)
        if attestation.get(FREEZE_FIELD):
            now = str(attestation[FREEZE_FIELD])
        else:
            now = _now_iso()
            attestation[FREEZE_FIELD] = now
        if extra_escalations:
            existing = list(attestation.get("class_escalations") or [])
            existing.extend(dict(e) for e in extra_escalations)
            attestation["class_escalations"] = existing
        normalized = dca.validate(attestation)
        c.execute(
            f"UPDATE items SET db_compatibility_attestation = {p} WHERE id = {p}",
            (dca.canonical_json(normalized), item_id),
        )
        c.commit()
        return now

    if conn is not None:
        return _stamp(conn)
    with db_helpers.connect() as owned:
        return _stamp(owned)


def clear_attestation_frozen_at(
    item_id: int,
    *,
    conn: Optional[Any] = None,
) -> bool:
    """Clear ``frozen_at`` so authored fields become editable again.

    Returns True when a stamp was cleared, False when no stamp existed.
    """
    from yoke_core.domain import db_compatibility_attestation as dca

    def _clear(c: Any) -> bool:
        p = _placeholder(c)
        row = c.execute(
            f"SELECT db_compatibility_attestation FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Item YOK-{item_id} not found")
        raw = row["db_compatibility_attestation"] if hasattr(row, "keys") else row[0]
        attestation = _safe_parse_dict(raw)
        if not attestation.get(FREEZE_FIELD):
            return False
        attestation.pop(FREEZE_FIELD, None)
        normalized = dca.validate(attestation)
        c.execute(
            f"UPDATE items SET db_compatibility_attestation = {p} WHERE id = {p}",
            (dca.canonical_json(normalized), item_id),
        )
        c.commit()
        return True

    if conn is not None:
        return _clear(conn)
    with db_helpers.connect() as owned:
        return _clear(owned)


__all__ = [
    "clear_attestation_frozen_at",
    "stamp_attestation_frozen_at",
]

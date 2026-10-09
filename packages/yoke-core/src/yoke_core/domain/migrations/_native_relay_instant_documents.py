"""Permanent finite clock repairs for mutable relay observations.

No recursive timestamp guessing: model retirement calendar labels and opaque
payloads remain unchanged. Owner-fact fallback is historical conversion only.
"""

from typing import Any

from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.migrations._native_instant_documents import (
    DocumentUpdate,
    _add,
    _clock,
    _document,
    _rows,
)


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(
            "instant_relay_document_shape_unreadable: declared relay observation "
            "is not an object. Recovery: inspect its restored owner document "
            "before rehearsal; no document or storage type changed."
        )
    return value


def _repair(conn: Any, doc: dict[str, Any], fields: tuple[str, ...], facts) -> bool:
    changed = False
    for field in fields:
        after = _clock(conn, doc.get(field), facts, optional=True)
        if field not in doc or doc[field] != after:
            doc[field] = after
            changed = True
    return changed


def prepare_relay_document_updates(conn: Any) -> list[DocumentUpdate]:
    """Prepare only the declared clock paths in existing relay documents."""
    updates: list[DocumentUpdate] = []
    for column in (
        "surface_plan_limits",
        "surface_native_models",
        "machine_capacity",
        "relay_health",
    ):
        for row in _rows(
            conn,
            "session_relays",
            "relay_id",
            column,
            ("last_seen_at", "first_seen_at"),
        ):
            doc = _document(row[1], "session_relays", row[0])
            facts = tuple(row[2:])
            changed = False
            if column in {"surface_plan_limits", "surface_native_models"}:
                for reading in doc.values():
                    reading = _object(reading)
                    changed |= _repair(conn, reading, ("observed_at",), facts)
                    if column == "surface_plan_limits" and "windows" in reading:
                        windows = reading["windows"]
                        if not isinstance(windows, list):
                            raise RuntimeError(
                                "instant_relay_windows_unreadable: restore and inspect the plan observation before rehearsal"
                            )
                        for window in windows:
                            changed |= _repair(
                                conn, _object(window), ("resets_at",), facts
                            )
            elif column == "machine_capacity":
                changed |= _repair(conn, doc, ("observed_at",), facts)
            else:
                for owner, fields in (
                    ("report_failure", ("first_failed_at", "last_failed_at")),
                    ("run_refusal", ("observed_at",)),
                ):
                    if owner in doc:
                        changed |= _repair(conn, _object(doc[owner]), fields, facts)
                if "quarantined_reports" in doc:
                    entries = doc["quarantined_reports"]
                    if not isinstance(entries, list):
                        raise RuntimeError(
                            "instant_relay_quarantines_unreadable: restore and inspect the health observation before rehearsal"
                        )
                    for entry in entries:
                        changed |= _repair(
                            conn, _object(entry), ("quarantined_at",), facts
                        )
            if changed:
                _add(
                    updates,
                    "session_relays",
                    "relay_id",
                    row,
                    column,
                    dumps_compact(doc),
                )
    return updates

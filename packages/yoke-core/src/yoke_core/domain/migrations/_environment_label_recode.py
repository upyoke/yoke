"""Label-era environment recodes shared by the reference-unification entry.

Underscore-prefixed so history discovery never treats it as an entry;
it lives inside the migrations package because it is part of that
entry's permanent behavior.
"""

from __future__ import annotations

import json
from typing import Any

#: Canonical environment names for the label era's long forms.
CANONICAL_ENVIRONMENT_NAMES = {"production": "prod", "staging": "stage"}

RECEIPT_EVENT_NAME = "FleetMigrationPreflightPassed"


def fetch_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(c[0]) for c in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def marker(conn: Any) -> str:
    from yoke_core.domain import db_backend
    return "%s" if db_backend.connection_is_postgres(conn) else "?"

def recode_label_column(conn: Any, table: str, column: str) -> None:
    p = marker(conn)
    for legacy, canonical in CANONICAL_ENVIRONMENT_NAMES.items():
        conn.execute(
            f"UPDATE \"{table}\" SET \"{column}\" = {p} "
            f"WHERE \"{column}\" = {p}",
            (canonical, legacy),
        )


def recode_environment_values(node: Any) -> bool:
    """Rewrite long-form environment labels held under environment keys."""
    changed = False
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                key in {"active_env", "target_env", "environment"}
                and isinstance(value, str)
                and value.lower() in CANONICAL_ENVIRONMENT_NAMES
            ):
                node[key] = CANONICAL_ENVIRONMENT_NAMES[value.lower()]
                changed = True
            else:
                changed = recode_environment_values(value) or changed
    elif isinstance(node, list):
        for child in node:
            changed = recode_environment_values(child) or changed
    return changed


def recode_json_column(conn: Any, table: str, key: str, column: str) -> None:
    p = marker(conn)
    rows = fetch_rows(conn.execute(
        f"SELECT \"{key}\" AS row_key, \"{column}\" AS doc FROM \"{table}\" "
        f"WHERE \"{column}\" LIKE '%production%' "
        f"OR \"{column}\" LIKE '%staging%'",
    ))
    for row in rows:
        try:
            doc = json.loads(row["doc"])
        except (TypeError, ValueError):
            continue
        if recode_environment_values(doc):
            conn.execute(
                f"UPDATE \"{table}\" SET \"{column}\" = {p} "
                f"WHERE \"{key}\" = {p}",
                (json.dumps(doc, separators=(",", ":")), row["row_key"]),
            )


def recode_pin_capability_keys(conn: Any) -> None:
    """Re-key release-pin environment maps onto canonical environment names."""
    p = marker(conn)
    rows = fetch_rows(conn.execute(
        f"SELECT id, settings FROM project_capabilities WHERE type = {p}",
        ("release_pin",),
    ))
    for row in rows:
        try:
            settings = json.loads(row["settings"] or "{}")
        except (TypeError, ValueError):
            continue
        changed = False
        for map_key in ("branch_by_environment", "environment_by_target"):
            mapping = settings.get(map_key)
            if not isinstance(mapping, dict):
                continue
            for legacy, canonical in CANONICAL_ENVIRONMENT_NAMES.items():
                if legacy in mapping and canonical not in mapping:
                    mapping[canonical] = mapping.pop(legacy)
                    changed = True
        if changed:
            conn.execute(
                f"UPDATE project_capabilities SET settings = {p} "
                f"WHERE id = {p}",
                (json.dumps(settings, separators=(",", ":")), row["id"]),
            )


def recode_receipt_events(conn: Any) -> None:
    p = marker(conn)
    rows = fetch_rows(conn.execute(
        f"SELECT id, envelope FROM events WHERE event_name = {p}",
        (RECEIPT_EVENT_NAME,),
    ))
    for row in rows:
        try:
            envelope = json.loads(row["envelope"])
        except (TypeError, ValueError):
            continue
        if recode_environment_values(envelope):
            conn.execute(
                f"UPDATE events SET envelope = {p} WHERE id = {p}",
                (json.dumps(envelope, separators=(",", ":")), row["id"]),
            )

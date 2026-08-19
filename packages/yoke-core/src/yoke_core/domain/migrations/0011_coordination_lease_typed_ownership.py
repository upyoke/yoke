"""Backfill typed owners on coordination leases.

``session_id`` stays as acquire-time registration. The holder is
``owner_kind`` plus the matching owner column. Rows that already carry
a typed owner are skipped. Anonymous rehearsal registration becomes
item-owned on the declared migration item for that lease key.

Column ADD IF NOT EXISTS here is ordering insurance so rehearsal
against a current dump is self-contained. Boot converge owns the
same columns via ``schema_coordination_lease_columns``.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _table_exists,
)


ANONYMOUS_REGISTRATION = "rehearse"
LEASE_KEY_PREFIX = "LIVE_DB_MIGRATION:"


def apply(conn: Any) -> None:
    if not _table_exists(conn, "coordination_leases"):
        return
    for column, ddl in (
        ("owner_kind", "TEXT NOT NULL DEFAULT 'session'"),
        ("owner_item_id", "INTEGER DEFAULT NULL"),
        ("owner_session_id", "TEXT DEFAULT NULL"),
        ("owner_work_claim_id", "INTEGER DEFAULT NULL"),
        ("released_by_session_id", "TEXT DEFAULT NULL"),
        ("released_by_actor_id", "TEXT DEFAULT NULL"),
    ):
        _add_column_if_not_exists(conn, "coordination_leases", column, ddl)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coordination_leases_owner_item "
        "ON coordination_leases(owner_item_id)"
    )
    rows = conn.execute(
        "SELECT id, project_id, lease_key, session_id, owner_kind, "
        "owner_item_id, owner_session_id, owner_work_claim_id "
        "FROM coordination_leases"
    ).fetchall()
    for row in rows:
        _backfill_row(conn, row)


def _has_typed_owner(row: Any) -> bool:
    """True when live code already wrote a typed owner; never rewrite those."""
    if row["owner_item_id"] is not None:
        return True
    if row["owner_session_id"]:
        return True
    return row["owner_work_claim_id"] is not None


def _backfill_row(conn: Any, row: Any) -> None:
    if _has_typed_owner(row):
        return
    session_id = str(row["session_id"] or "")
    if session_id == ANONYMOUS_REGISTRATION:
        item_id = _item_for_lease(conn, int(row["project_id"]), str(row["lease_key"]))
        conn.execute(
            "UPDATE coordination_leases SET owner_kind='item', "
            "owner_item_id=%s, owner_session_id=NULL, "
            "owner_work_claim_id=NULL WHERE id=%s",
            (item_id, int(row["id"])),
        )
        return
    conn.execute(
        "UPDATE coordination_leases SET owner_kind='session', "
        "owner_session_id=%s, owner_item_id=NULL, "
        "owner_work_claim_id=NULL WHERE id=%s",
        (session_id, int(row["id"])),
    )


def _item_for_lease(conn: Any, project_id: int, lease_key: str) -> int | None:
    if not lease_key.startswith(LEASE_KEY_PREFIX):
        return None
    model_name = lease_key[len(LEASE_KEY_PREFIX):]
    if not model_name or not _table_exists(conn, "items"):
        return None
    rows = conn.execute(
        "SELECT id, db_mutation_profile FROM items "
        "WHERE project_id=%s ORDER BY id DESC",
        (project_id,),
    ).fetchall()
    for item in rows:
        raw = item["db_mutation_profile"]
        try:
            payload = raw if isinstance(raw, dict) else json.loads(str(raw or ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("state") != "declared":
            continue
        if str(payload.get("model_name") or "") == model_name:
            return int(item["id"])
    return None

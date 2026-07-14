"""Deterministic, secret-free source-authority comparison receipts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg import sql

from yoke_core.domain.schema_fingerprint import fingerprint_portable_postgres_schema
from yoke_core.domain.source_authority_overlay_receipts import (
    capability_secrets_receipt,
    filter_typed_receipt,
    project_capabilities_receipt,
)


NORMALIZATION_SCHEMA = "yoke.portable-authority/v1"
EXCLUDED_TABLE_OWNERSHIP = {
    "destination_convergence": frozenset({
        "actor_external_identities", "actor_invites", "actor_labels",
        "actor_org_roles", "actor_project_roles", "actors",
        "api_token_audit", "api_tokens", "web_sessions",
    }),
    "destination_rebind": frozenset({"organizations"}),
    "destination_overlay": frozenset({
        "github_app_installations", "project_github_repo_bindings",
    }),
    "separate_receipt_plane": frozenset({
        "capability_secrets", "project_capabilities",
    }),
    "retired_nonportable": frozenset({
        "coordination_leases", "harness_sessions", "merge_locks",
        "session_tool_calls", "work_claims",
    }),
}
NORMALIZED_EXCLUDED_TABLES = frozenset().union(
    *EXCLUDED_TABLE_OWNERSHIP.values()
)


def authority_receipt(
    conn: object, *, include_content_digests: bool = False,
) -> dict[str, Any]:
    """Return bounded metadata or one streaming full-content receipt."""
    tables = _base_tables(conn)
    excluded_tables = sorted(set(tables) & NORMALIZED_EXCLUDED_TABLES)
    portable_tables = [table for table in tables if table not in excluded_tables]
    table_rows = {
        table: _table_receipt(
            conn, table, include_content_digest=include_content_digests,
        )
        for table in portable_tables
    }
    strategies = _strategy_receipts(conn) if "strategy_docs" in tables else []
    sequences = _sequence_receipts(conn, excluded_tables=set(excluded_tables))
    catalog_text = "\n".join(portable_tables) + "\n--sequences--\n" + "\n".join(
        entry["name"] for entry in sequences
    )
    database_catalog_text = "\n".join(tables)
    body: dict[str, Any] = {
        "normalization": {
            "schema": NORMALIZATION_SCHEMA,
            "excluded_tables": excluded_tables,
            "excluded_table_ownership": {
                owner: sorted(set(tables) & set(owned))
                for owner, owned in EXCLUDED_TABLE_OWNERSHIP.items()
            },
            "project_capability_types": "separate-receipt-plane",
            "capability_secret_types": "separate-receipt-plane",
        },
        "schema_fingerprint": fingerprint_portable_postgres_schema(conn),
        "database_table_catalog": tables,
        "database_table_catalog_digest": _sha256_text(database_catalog_text),
        "portable_table_catalog": portable_tables,
        "portable_table_catalog_digest": _sha256_text(catalog_text),
        "tables": table_rows,
        "strategy_rows": strategies,
        "sequences": sequences,
        "content_digests_included": include_content_digests,
        "event_max_created_at": (
            _event_max_created_at(conn) if "events" in tables else None
        ),
    }
    body["project_capabilities"] = (
        project_capabilities_receipt(conn)
        if "project_capabilities" in tables else None
    )
    body["capability_secrets"] = (
        capability_secrets_receipt(conn)
        if "capability_secrets" in tables else None
    )
    digest_body = dict(body)
    if body["capability_secrets"] is not None:
        # Secret rows never enter the archive. Whole-authority equality uses
        # the canonical restored-empty plane while the populated source plane
        # remains adjacent audit evidence for overlay coverage.
        digest_body["capability_secrets"] = filter_typed_receipt(
            body["capability_secrets"], frozenset(),
        )
    body["receipt_digest"] = _sha256_text(
        json.dumps(digest_body, sort_keys=True, separators=(",", ":"))
    )
    return body


def _base_tables(conn: object) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
    ]


def _table_receipt(
    conn: object, table: str, *, include_content_digest: bool,
) -> dict[str, Any]:
    columns = [
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,),
        ).fetchall()
    ]
    identifier = sql.Identifier(table)
    projections = [sql.SQL("COUNT(*)")]
    names = ["count"]
    for name in ("id", "updated_at"):
        if name in columns:
            projections.append(
                sql.SQL("MAX({})::text").format(sql.Identifier(name))
            )
            names.append(f"max_{name}")
    values = conn.execute(
        sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(projections), identifier,
        )
    ).fetchone()
    receipt: dict[str, Any] = {
        name: (int(value) if name == "count" else value)
        for name, value in zip(names, values)
    }
    if include_content_digest:
        receipt["digest"] = streaming_table_digest(conn, table)
    return receipt


def streaming_table_digest(conn: object, table: str) -> str:
    """Hash one table with O(1) client memory and no server-side row sort.

    Row SHA256 values are added modulo 2**256, producing a deterministic
    multiset digest independent of physical/restore order. A named cursor
    bounds each client fetch; compact status/begin receipts never call this.
    """
    cursor = conn.cursor(name=f"source_cutover_{table[:40]}")
    try:
        cursor.execute(
            sql.SQL("SELECT row_to_json(t)::text FROM {} AS t").format(
                sql.Identifier(table)
            )
        )
        aggregate = 0
        modulus = 1 << 256
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for row in rows:
                row_digest = hashlib.sha256(str(row[0]).encode("utf-8")).digest()
                aggregate = (aggregate + int.from_bytes(row_digest, "big")) % modulus
        return aggregate.to_bytes(32, "big").hex()
    finally:
        cursor.close()


def _strategy_receipts(conn: object) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT project_id, slug, updated_at, content FROM strategy_docs "
        "ORDER BY project_id, slug"
    ).fetchall()
    return [
        {
            "project_id": int(row[0]),
            "slug": str(row[1]),
            "updated_at": str(row[2]),
            "content_sha256": _sha256_text(str(row[3])),
        }
        for row in rows
    ]


def _sequence_receipts(
    conn: object, *, excluded_tables: set[str],
) -> list[dict[str, Any]]:
    owned = [
        (str(row[0]), None if row[1] is None else str(row[1]))
        for row in conn.execute(
            "SELECT seq.relname, owner.relname "
            "FROM pg_catalog.pg_class seq "
            "JOIN pg_catalog.pg_namespace ns ON ns.oid = seq.relnamespace "
            "LEFT JOIN pg_catalog.pg_depend dep ON dep.objid = seq.oid "
            "AND dep.deptype IN ('a', 'i') "
            "LEFT JOIN pg_catalog.pg_class owner ON owner.oid = dep.refobjid "
            "WHERE ns.nspname = current_schema() AND seq.relkind = 'S' "
            "ORDER BY seq.relname"
        ).fetchall()
    ]
    receipts = []
    for name, owner_table in owned:
        if owner_table in excluded_tables:
            continue
        row = conn.execute(
            sql.SQL("SELECT last_value, is_called FROM {}").format(
                sql.Identifier(name)
            )
        ).fetchone()
        receipts.append(
            {
                "name": name,
                "owner_table": owner_table,
                "last_value": int(row[0]),
                "is_called": bool(row[1]),
            }
        )
    return receipts


def _event_max_created_at(conn: object) -> str | None:
    value = conn.execute("SELECT MAX(created_at)::text FROM events").fetchone()[0]
    return None if value is None else str(value)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "EXCLUDED_TABLE_OWNERSHIP",
    "NORMALIZATION_SCHEMA",
    "NORMALIZED_EXCLUDED_TABLES",
    "authority_receipt",
    "capability_secrets_receipt",
    "filter_typed_receipt",
    "project_capabilities_receipt",
    "streaming_table_digest",
]

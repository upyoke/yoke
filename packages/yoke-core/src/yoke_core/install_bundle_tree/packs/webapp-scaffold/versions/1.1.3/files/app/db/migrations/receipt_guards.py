"""Exact SQLite guards for append-only migration adoption receipts."""

from __future__ import annotations

import json


RECEIPT_TABLE = "migration_adoption_receipts"
RECEIPT_COLUMNS = {
    "receipt_id",
    "manifest_sha256",
    "engine_version",
    "source_artifact",
    "source_sha256",
    "source_commit",
    "adopted_by",
    "artifact_verifier",
    "artifact_verification_sha256",
    "adopted_entries_json",
    "recorded_at",
}
RECEIPT_GUARDS = {
    "migration_adoption_receipts_no_update": "UPDATE",
    "migration_adoption_receipts_no_delete": "DELETE",
}
LEDGER_TABLE = "schema_version"
LEDGER_GUARDS = {
    "migration_membership_guard_update": "UPDATE",
    "migration_membership_guard_delete": "DELETE",
}
LEDGER_TRANSITION_GUARD = "migration_membership_guard_update"


def _receipt_table_sql() -> str:
    return (
        f"CREATE TABLE {RECEIPT_TABLE} ("
        "receipt_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "manifest_sha256 TEXT NOT NULL UNIQUE, engine_version TEXT NOT NULL, "
        "source_artifact TEXT NOT NULL, source_sha256 TEXT NOT NULL, "
        "source_commit TEXT NOT NULL, adopted_by TEXT NOT NULL, "
        "artifact_verifier TEXT NOT NULL, "
        "artifact_verification_sha256 TEXT NOT NULL, "
        "adopted_entries_json TEXT NOT NULL, "
        "recorded_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )


def _guard_sql(name: str, operation: str) -> str:
    return (
        f"CREATE TRIGGER {name} BEFORE {operation} ON {RECEIPT_TABLE} "
        "BEGIN SELECT RAISE(ABORT, "
        "'migration adoption receipts are append-only'); END"
    )


def _ledger_guard_sql(name: str, operation: str) -> str:
    if operation == "DELETE":
        return (
            f"CREATE TRIGGER {name} BEFORE DELETE ON {LEDGER_TABLE} FOR EACH ROW "
            "BEGIN SELECT RAISE(ABORT, "
            "'applied migration membership is immutable'); END"
        )
    return (
        f"CREATE TRIGGER {name} BEFORE UPDATE OF migration_name, version, "
        f"minimum_serving_version, content_sha256 ON {LEDGER_TABLE} FOR EACH ROW "
        "WHEN (NEW.migration_name IS NOT OLD.migration_name "
        "OR NEW.version IS NOT OLD.version "
        "OR NEW.minimum_serving_version IS NOT OLD.minimum_serving_version "
        "OR NEW.content_sha256 IS NOT OLD.content_sha256) AND NOT ("
        "OLD.version IS NEW.version AND "
        "(OLD.migration_name IS NULL OR OLD.migration_name IS NEW.migration_name) "
        "AND (OLD.minimum_serving_version IS NULL OR "
        "OLD.minimum_serving_version IS NEW.minimum_serving_version) "
        "AND (OLD.content_sha256 IS NULL OR "
        "OLD.content_sha256 IS NEW.content_sha256) "
        "AND NEW.migration_name IS NOT NULL "
        "AND NEW.content_sha256 IS NOT NULL "
        f"AND EXISTS (SELECT 1 FROM {RECEIPT_TABLE} AS receipt, "
        "json_each(receipt.adopted_entries_json) AS adopted "
        "WHERE json_extract(adopted.value, '$.name') = NEW.migration_name "
        "AND json_extract(adopted.value, '$.content_sha256') = "
        "NEW.content_sha256 AND "
        "json_extract(adopted.value, '$.minimum_serving_version') "
        "IS NEW.minimum_serving_version)) BEGIN SELECT RAISE(ABORT, "
        "'applied migration membership is immutable without matching receipt'); END"
    )


def _normalized_sql(value) -> str:
    return " ".join(str(value or "").split()).rstrip(";").casefold()


def adoption_receipt_guard_state(conn) -> dict:
    """Require each expected name to carry its exact append-only semantics."""
    table_present = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (RECEIPT_TABLE,),
        ).fetchone()
        is not None
    )
    table_sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (RECEIPT_TABLE,),
    ).fetchone()
    table_shape_ready = bool(
        table_sql_row
        and _normalized_sql(table_sql_row[0]) == _normalized_sql(_receipt_table_sql())
    )
    invalid = [] if table_present else sorted(RECEIPT_GUARDS)
    receipt_columns = (
        {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({RECEIPT_TABLE})").fetchall()
        }
        if table_present
        else set()
    )
    missing_columns = sorted(RECEIPT_COLUMNS - receipt_columns)
    unexpected_columns = sorted(receipt_columns - RECEIPT_COLUMNS)
    if missing_columns or unexpected_columns:
        invalid.append("migration_adoption_receipts_columns")
    if table_present and not table_shape_ready:
        invalid.append("migration_adoption_receipts_shape")
    if table_present:
        installed = {
            str(name): sql
            for name, sql in conn.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name=?",
                (RECEIPT_TABLE,),
            ).fetchall()
        }
        invalid.extend(
            name
            for name, operation in RECEIPT_GUARDS.items()
            if _normalized_sql(installed.get(name))
            != _normalized_sql(_guard_sql(name, operation))
        )
    installed_ledger = {
        str(name): sql
        for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
            (LEDGER_TABLE,),
        ).fetchall()
    }
    invalid_ledger = sorted(
        name
        for name, operation in LEDGER_GUARDS.items()
        if _normalized_sql(installed_ledger.get(name))
        != _normalized_sql(_ledger_guard_sql(name, operation))
    )
    invalid.extend(invalid_ledger)
    return {
        "adoption_receipt_table_present": table_present,
        "adoption_receipt_guards_ready": table_present and not invalid,
        "missing_adoption_receipt_guards": sorted(invalid),
        "missing_adoption_receipt_columns": missing_columns,
        "unexpected_adoption_receipt_columns": unexpected_columns,
        "adoption_receipt_table_shape_ready": table_shape_ready,
        "adoption_ledger_transition_guard_ready": not invalid_ledger,
    }


def ensure_adoption_receipt_guards(conn) -> None:
    """Create the receipt ledger and replace every guard with exact SQL."""
    conn.execute(
        _receipt_table_sql().replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
    )
    receipt_columns = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({RECEIPT_TABLE})").fetchall()
    }
    missing_columns = RECEIPT_COLUMNS - receipt_columns
    unexpected_columns = receipt_columns - RECEIPT_COLUMNS
    if missing_columns or unexpected_columns:
        raise RuntimeError(
            "Migration adoption receipt table has an incompatible shape; "
            f"missing={sorted(missing_columns)!r}, "
            f"unexpected={sorted(unexpected_columns)!r}"
        )
    if not adoption_receipt_guard_state(conn)["adoption_receipt_table_shape_ready"]:
        raise RuntimeError(
            "Migration adoption receipt table has an incompatible exact shape"
        )
    for name, operation in RECEIPT_GUARDS.items():
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        conn.execute(_guard_sql(name, operation))
    for name, operation in LEDGER_GUARDS.items():
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        conn.execute(_ledger_guard_sql(name, operation))


def ensure_schema_version(
    conn,
    history,
    *,
    commit: bool = True,
    repair_adoption_guards: bool = False,
) -> None:
    """Converge ledger columns; repair guards only with explicit authority."""
    ledger_preexisting = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone()
        is not None
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(schema_version)").fetchall()
    }
    if "migration_name" not in columns:
        conn.execute("ALTER TABLE schema_version ADD COLUMN migration_name TEXT")
    if "minimum_serving_version" not in columns:
        conn.execute(
            "ALTER TABLE schema_version ADD COLUMN minimum_serving_version TEXT"
        )
    if "content_sha256" not in columns:
        conn.execute("ALTER TABLE schema_version ADD COLUMN content_sha256 TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "schema_version_migration_name_uq ON schema_version(migration_name)"
    )
    if repair_adoption_guards or not ledger_preexisting:
        ensure_adoption_receipt_guards(conn)
    if commit:
        conn.commit()


def require_adoption_receipt_guards(conn) -> dict:
    """Refuse mutation while exact receipt and membership guards are absent."""
    state = adoption_receipt_guard_state(conn)
    if state["adoption_receipt_guards_ready"]:
        return state
    raise RuntimeError(
        "Migration identity guards are absent or changed; normal boot will not "
        "repair an existing ledger. Run the project-owned, artifact-verified "
        f"adoption path first: {state['missing_adoption_receipt_guards']!r}"
    )


def record_adoption_receipt(
    conn,
    manifest: dict,
    adopted_entries: list[dict],
    adopted_by: str,
    artifact_verification: dict,
) -> dict | None:
    """Append evidence before the receipted ledger transitions it authorizes."""
    if not adopted_entries:
        return None
    require_adoption_receipt_guards(conn)
    artifact = manifest["artifact"]
    adopted_json = json.dumps(
        adopted_entries,
        separators=(",", ":"),
        sort_keys=True,
    )
    cursor = conn.execute(
        f"INSERT INTO {RECEIPT_TABLE} ("
        "manifest_sha256, engine_version, source_artifact, source_sha256, "
        "source_commit, adopted_by, artifact_verifier, "
        "artifact_verification_sha256, adopted_entries_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            manifest["manifest_sha256"],
            artifact["engine_version"],
            artifact["source_artifact"],
            artifact["source_sha256"],
            artifact["source_commit"],
            adopted_by,
            artifact_verification["verifier"],
            artifact_verification["verification_receipt_sha256"],
            adopted_json,
        ),
    )
    return {
        "receipt_id": int(cursor.lastrowid),
        "manifest_sha256": manifest["manifest_sha256"],
        "source_sha256": artifact["source_sha256"],
        "source_commit": artifact["source_commit"],
        "adopted_by": adopted_by,
        "artifact_verifier": artifact_verification["verifier"],
        "artifact_verification_sha256": artifact_verification[
            "verification_receipt_sha256"
        ],
    }


__all__ = [
    "RECEIPT_GUARDS",
    "RECEIPT_COLUMNS",
    "RECEIPT_TABLE",
    "LEDGER_GUARDS",
    "LEDGER_TRANSITION_GUARD",
    "adoption_receipt_guard_state",
    "ensure_adoption_receipt_guards",
    "ensure_schema_version",
    "record_adoption_receipt",
    "require_adoption_receipt_guards",
]

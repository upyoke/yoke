"""Project-neutral additive schema and evidence writer for digest adoption."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.migration_content_adoption import AdoptionRecord
from yoke_core.domain.migration_ledger_contract import LedgerContract
from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ADOPTION_EVIDENCE_GUARD_PREFIX = "migration_evidence_guard_"
_APPEND_ONLY_MESSAGE = "migration adoption evidence is append-only"


@dataclass(frozen=True)
class AdoptionEvidenceContract:
    """Declared identifiers for one project's append-only adoption evidence."""

    table: str
    entry_column: str = "migration_name"
    content_digest_column: str = "content_sha256"
    engine_version_column: str = "artifact_engine_version"
    source_artifact_column: str = "source_artifact"
    source_digest_column: str = "source_sha256"
    source_commit_column: str = "source_commit"
    manifest_digest_column: str = "manifest_sha256"
    actor_column: str = "adopted_by"
    timestamp_column: str = "adopted_at"

    def __post_init__(self) -> None:
        invalid = [
            name
            for name, value in self.__dict__.items()
            if not _IDENTIFIER.fullmatch(value)
        ]
        if invalid:
            raise ValueError(
                "migration content evidence has unsafe SQL identifier(s): "
                + ", ".join(invalid)
            )


def converge_migration_content_schema(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> None:
    """Add nullable digest metadata and the project-declared evidence table.

    No commit is performed.  A pre-deploy admin adapter commits this additive
    step before adoption so the currently deployed build remains compatible.
    """
    _add_column_if_not_exists(
        conn,
        ledger.table,
        ledger.digest_column,
        "TEXT",
    )
    execute_schema_script(
        conn,
        f"""
        CREATE TABLE IF NOT EXISTS {evidence.table} (
            {evidence.entry_column} TEXT PRIMARY KEY,
            {evidence.content_digest_column} TEXT NOT NULL,
            {evidence.engine_version_column} TEXT NOT NULL,
            {evidence.source_artifact_column} TEXT NOT NULL,
            {evidence.source_digest_column} TEXT NOT NULL,
            {evidence.source_commit_column} TEXT NOT NULL,
            {evidence.manifest_digest_column} TEXT NOT NULL,
            {evidence.actor_column} TEXT NOT NULL,
            {evidence.timestamp_column} TEXT NOT NULL
        );
        """,
    )
    _ensure_adoption_evidence_immutability(conn, evidence)


def _immutability_object_name(table: str) -> str:
    """Return a short, collision-resistant SQL object-name stem."""
    digest = hashlib.sha256(table.encode("utf-8")).hexdigest()[:16]
    return f"{ADOPTION_EVIDENCE_GUARD_PREFIX}{digest}"


def _ensure_adoption_evidence_immutability(
    conn: Any,
    evidence: AdoptionEvidenceContract,
) -> None:
    """Restore database-enforced UPDATE/DELETE refusal idempotently."""
    stem = _immutability_object_name(evidence.table)
    if not db_backend.connection_is_postgres(conn):
        for operation in ("UPDATE", "DELETE"):
            conn.execute(f"DROP TRIGGER IF EXISTS {stem}_{operation.lower()}")
            conn.execute(
                f"CREATE TRIGGER {stem}_{operation.lower()} "
                f"BEFORE {operation} ON {evidence.table} BEGIN "
                f"SELECT RAISE(ABORT, '{_APPEND_ONLY_MESSAGE}'); END"
            )
        return

    function_name = f"{stem}_fn"
    conn.execute(
        f"""
        CREATE OR REPLACE FUNCTION {function_name}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $migration_evidence_guard$
        BEGIN
            RAISE EXCEPTION '{_APPEND_ONLY_MESSAGE}';
            RETURN NULL;
        END;
        $migration_evidence_guard$
        """
    )
    conn.execute(f"DROP TRIGGER IF EXISTS {stem} ON {evidence.table}")
    conn.execute(
        f"CREATE TRIGGER {stem} BEFORE UPDATE OR DELETE ON {evidence.table} "
        f"FOR EACH ROW EXECUTE FUNCTION {function_name}()"
    )
    conn.execute(f"DROP TRIGGER IF EXISTS {stem}_truncate ON {evidence.table}")
    conn.execute(
        f"CREATE TRIGGER {stem}_truncate BEFORE TRUNCATE ON {evidence.table} "
        f"FOR EACH STATEMENT EXECUTE FUNCTION {function_name}()"
    )


def adoption_evidence_is_immutable(
    conn: Any,
    evidence: AdoptionEvidenceContract,
) -> bool:
    """Return whether the declared table has every expected mutation guard."""
    stem = _immutability_object_name(evidence.table)
    if not db_backend.connection_is_postgres(conn):
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name = ?",
            (evidence.table,),
        ).fetchall()
        actual = {str(row[0]): _normalized_sql(row[1]) for row in rows}
        return all(
            actual.get(f"{stem}_{operation.lower()}")
            == _normalized_sql(
                f"CREATE TRIGGER {stem}_{operation.lower()} "
                f"BEFORE {operation} ON {evidence.table} BEGIN "
                f"SELECT RAISE(ABORT, '{_APPEND_ONLY_MESSAGE}'); END"
            )
            for operation in ("UPDATE", "DELETE")
        )

    rows = conn.execute(
        "SELECT trigger.tgname, procedure.proname, trigger.tgenabled, "
        "trigger.tgtype::int, procedure.prosrc, language.lanname, "
        "pg_catalog.pg_get_function_result(procedure.oid) "
        "FROM pg_trigger AS trigger "
        "JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid "
        "JOIN pg_language AS language ON language.oid = procedure.prolang "
        "WHERE trigger.tgrelid = to_regclass(%s) "
        "AND NOT trigger.tgisinternal",
        (evidence.table,),
    ).fetchall()
    function_name = f"{stem}_fn"
    by_name = {str(row[0]): row for row in rows}
    expected_body = _normalized_sql(
        f"BEGIN RAISE EXCEPTION '{_APPEND_ONLY_MESSAGE}'; RETURN NULL; END;"
    )
    return all(
        row is not None
        and str(row[1]) == function_name
        and str(row[2]) == "O"
        and int(row[3]) == trigger_type
        and _normalized_sql(row[4]) == expected_body
        and str(row[5]) == "plpgsql"
        and str(row[6]) == "trigger"
        for row, trigger_type in (
            (by_name.get(stem), 27),  # BEFORE UPDATE OR DELETE FOR EACH ROW
            (by_name.get(f"{stem}_truncate"), 34),  # BEFORE TRUNCATE STATEMENT
        )
    )


def _normalized_sql(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().rstrip(";").casefold()


def migration_content_schema_is_prepared(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> bool:
    """Return whether the additive digest/evidence schema is present."""
    from yoke_core.domain.schema_common import _column_exists, _table_exists

    if not _column_exists(conn, ledger.table, ledger.digest_column):
        return False
    if not _table_exists(conn, evidence.table):
        return False
    columns_ready = all(
        _column_exists(conn, evidence.table, column)
        for column in (
            evidence.entry_column,
            evidence.content_digest_column,
            evidence.engine_version_column,
            evidence.source_artifact_column,
            evidence.source_digest_column,
            evidence.source_commit_column,
            evidence.manifest_digest_column,
            evidence.actor_column,
            evidence.timestamp_column,
        )
    )
    return columns_ready and adoption_evidence_is_immutable(conn, evidence)


def prepare_migration_content_schema(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> None:
    """Commit the additive pre-deploy schema as its own rollout phase."""
    try:
        converge_migration_content_schema(conn, ledger, evidence)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def write_adoption_evidence(
    conn: Any,
    records: Tuple[AdoptionRecord, ...],
    evidence: AdoptionEvidenceContract,
) -> None:
    """Append project-declared evidence inside the adoption transaction."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    columns = (
        evidence.entry_column,
        evidence.content_digest_column,
        evidence.engine_version_column,
        evidence.source_artifact_column,
        evidence.source_digest_column,
        evidence.source_commit_column,
        evidence.manifest_digest_column,
        evidence.actor_column,
        evidence.timestamp_column,
    )
    placeholders = ", ".join(marker for _column in columns)
    for record in records:
        conn.execute(
            f"INSERT INTO {evidence.table} ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            (
                record.entry_name,
                record.content_sha256,
                record.artifact_engine_version,
                record.source_artifact,
                record.source_sha256,
                record.source_commit,
                record.manifest_sha256,
                record.adopted_by,
                record.adopted_at,
            ),
        )


def adoption_evidence_writer(
    evidence: AdoptionEvidenceContract,
) -> Callable[[Any, Tuple[AdoptionRecord, ...]], None]:
    """Bind a declared evidence table for the generic adoption API."""
    return lambda conn, records: write_adoption_evidence(conn, records, evidence)


def adoption_evidence_verifier(
    evidence: AdoptionEvidenceContract,
) -> Callable[[Any], bool]:
    """Bind database-enforced immutability for the generic adoption API."""
    return lambda conn: adoption_evidence_is_immutable(conn, evidence)


__all__ = [
    "ADOPTION_EVIDENCE_GUARD_PREFIX",
    "AdoptionEvidenceContract",
    "adoption_evidence_is_immutable",
    "adoption_evidence_verifier",
    "adoption_evidence_writer",
    "converge_migration_content_schema",
    "migration_content_schema_is_prepared",
    "prepare_migration_content_schema",
    "write_adoption_evidence",
]

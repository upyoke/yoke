"""Database enforcement for evidence-bound legacy digest adoption."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from yoke_core.domain import db_backend

if TYPE_CHECKING:
    from yoke_core.domain.migration_content_schema import AdoptionEvidenceContract
    from yoke_core.domain.migration_ledger_contract import LedgerContract


ADOPTION_TRANSITION_GUARD_PREFIX = "migration_adoption_transition_guard_"
_MISSING_EVIDENCE_MESSAGE = (
    "migration digest adoption requires matching immutable evidence"
)


def _guard_object_name(
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> str:
    """Return a stable object name for one declared ledger/evidence pair."""
    identity = "\0".join(
        (
            ledger.table,
            ledger.entry_column,
            ledger.digest_column,
            evidence.table,
            evidence.entry_column,
            evidence.content_digest_column,
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{ADOPTION_TRANSITION_GUARD_PREFIX}{digest}"


def _sqlite_guard_sql(
    name: str,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> str:
    return (
        f"CREATE TRIGGER {name} BEFORE UPDATE OF {ledger.digest_column} "
        f"ON {ledger.table} FOR EACH ROW "
        f"WHEN OLD.{ledger.digest_column} IS NULL "
        f"AND NEW.{ledger.digest_column} IS NOT NULL "
        f"AND NOT EXISTS (SELECT 1 FROM {evidence.table} "
        f"WHERE {evidence.entry_column} = NEW.{ledger.entry_column} "
        f"AND {evidence.content_digest_column} = NEW.{ledger.digest_column}) "
        f"BEGIN SELECT RAISE(ABORT, '{_MISSING_EVIDENCE_MESSAGE}'); END"
    )


def ensure_adoption_transition_guard(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> None:
    """Require matching evidence for each legacy NULL-to-digest update.

    A newly applied migration inserts its digest with its membership row, so
    the guard deliberately covers UPDATE only. Adoption appends evidence and
    then performs the conditional update in one transaction.
    """
    name = _guard_object_name(ledger, evidence)
    if not db_backend.connection_is_postgres(conn):
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        conn.execute(_sqlite_guard_sql(name, ledger, evidence))
        return

    function_name = f"{name}_fn"
    conn.execute(
        f"""
        CREATE OR REPLACE FUNCTION {function_name}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $migration_adoption_transition_guard$
        BEGIN
            IF OLD.{ledger.digest_column} IS NULL
               AND NEW.{ledger.digest_column} IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM {evidence.table}
                   WHERE {evidence.entry_column} = NEW.{ledger.entry_column}
                     AND {evidence.content_digest_column} = NEW.{ledger.digest_column}
               )
            THEN
                RAISE EXCEPTION '{_MISSING_EVIDENCE_MESSAGE}';
            END IF;
            RETURN NEW;
        END;
        $migration_adoption_transition_guard$
        """
    )
    conn.execute(f"DROP TRIGGER IF EXISTS {name} ON {ledger.table}")
    conn.execute(
        f"CREATE TRIGGER {name} BEFORE UPDATE OF {ledger.digest_column} "
        f"ON {ledger.table} FOR EACH ROW EXECUTE FUNCTION {function_name}()"
    )


def adoption_transition_guard_is_enforced(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> bool:
    """Return whether the exact declared transition guard is active."""
    name = _guard_object_name(ledger, evidence)
    if not db_backend.connection_is_postgres(conn):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = ? AND tbl_name = ?",
            (name, ledger.table),
        ).fetchone()
        return row is not None and _normalized_sql(row[0]) == _normalized_sql(
            _sqlite_guard_sql(name, ledger, evidence)
        )

    row = conn.execute(
        "SELECT procedure.proname, trigger.tgenabled, trigger.tgtype::int, "
        "procedure.prosrc, language.lanname, "
        "pg_catalog.pg_get_function_result(procedure.oid), "
        "trigger.tgattr::text, attribute.attnum::text "
        "FROM pg_trigger AS trigger "
        "JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid "
        "JOIN pg_language AS language ON language.oid = procedure.prolang "
        "JOIN pg_attribute AS attribute "
        "ON attribute.attrelid = trigger.tgrelid AND attribute.attname = %s "
        "WHERE trigger.tgrelid = to_regclass(%s) "
        "AND trigger.tgname = %s AND NOT trigger.tgisinternal",
        (ledger.digest_column, ledger.table, name),
    ).fetchone()
    if row is None:
        return False
    function_name = f"{name}_fn"
    expected_body = _normalized_sql(
        f"""
        BEGIN
            IF OLD.{ledger.digest_column} IS NULL
               AND NEW.{ledger.digest_column} IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM {evidence.table}
                   WHERE {evidence.entry_column} = NEW.{ledger.entry_column}
                     AND {evidence.content_digest_column} = NEW.{ledger.digest_column}
               )
            THEN
                RAISE EXCEPTION '{_MISSING_EVIDENCE_MESSAGE}';
            END IF;
            RETURN NEW;
        END;
        """
    )
    return (
        str(row[0]) == function_name
        and str(row[1]) == "O"
        and int(row[2]) == 19  # BEFORE UPDATE FOR EACH ROW
        and _normalized_sql(row[3]) == expected_body
        and str(row[4]) == "plpgsql"
        and str(row[5]) == "trigger"
        and str(row[6]).strip() == str(row[7])
    )


def _normalized_sql(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().rstrip(";").casefold()


__all__ = [
    "ADOPTION_TRANSITION_GUARD_PREFIX",
    "adoption_transition_guard_is_enforced",
    "ensure_adoption_transition_guard",
]

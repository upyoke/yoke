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
_IMMUTABLE_MEMBERSHIP_MESSAGE = "applied migration membership is immutable"


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


def adoption_transition_guard_function_name(
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> str:
    """Return the PostgreSQL function owned by the declared guard."""
    return f"{_guard_object_name(ledger, evidence)}_fn"


def _sqlite_update_guard_sql(
    name: str,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> str:
    return (
        f"CREATE TRIGGER {name}_update BEFORE UPDATE OF {ledger.entry_column}, "
        f"{ledger.digest_column}, {ledger.serving_floor_column} "
        f"ON {ledger.table} FOR EACH ROW "
        f"WHEN NEW.{ledger.entry_column} IS NOT OLD.{ledger.entry_column} "
        f"OR NEW.{ledger.serving_floor_column} "
        f"IS NOT OLD.{ledger.serving_floor_column} "
        f"OR (OLD.{ledger.digest_column} IS NOT NULL "
        f"AND NEW.{ledger.digest_column} IS NOT OLD.{ledger.digest_column}) "
        f"BEGIN SELECT RAISE(ABORT, '{_IMMUTABLE_MEMBERSHIP_MESSAGE}'); END"
    )


def _sqlite_adoption_guard_sql(
    name: str,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> str:
    return (
        f"CREATE TRIGGER {name}_adopt BEFORE UPDATE OF {ledger.digest_column} "
        f"ON {ledger.table} FOR EACH ROW "
        f"WHEN OLD.{ledger.digest_column} IS NULL "
        f"AND NEW.{ledger.digest_column} IS NOT NULL "
        f"AND NOT EXISTS (SELECT 1 FROM {evidence.table} "
        f"WHERE {evidence.entry_column} = NEW.{ledger.entry_column} "
        f"AND {evidence.content_digest_column} = NEW.{ledger.digest_column}) "
        f"BEGIN SELECT RAISE(ABORT, '{_MISSING_EVIDENCE_MESSAGE}'); END"
    )


def _sqlite_delete_guard_sql(name: str, ledger: LedgerContract) -> str:
    return (
        f"CREATE TRIGGER {name}_delete BEFORE DELETE ON {ledger.table} "
        f"FOR EACH ROW BEGIN SELECT RAISE(ABORT, "
        f"'{_IMMUTABLE_MEMBERSHIP_MESSAGE}'); END"
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
        for suffix in ("update", "adopt", "delete"):
            conn.execute(f"DROP TRIGGER IF EXISTS {name}_{suffix}")
        conn.execute(_sqlite_update_guard_sql(name, ledger, evidence))
        conn.execute(_sqlite_adoption_guard_sql(name, ledger, evidence))
        conn.execute(_sqlite_delete_guard_sql(name, ledger))
        return

    function_name = adoption_transition_guard_function_name(ledger, evidence)
    conn.execute(
        f"""
        CREATE OR REPLACE FUNCTION {function_name}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $migration_adoption_transition_guard$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION '{_IMMUTABLE_MEMBERSHIP_MESSAGE}';
            END IF;
            IF NEW.{ledger.entry_column} IS DISTINCT FROM OLD.{ledger.entry_column}
               OR NEW.{ledger.serving_floor_column}
                  IS DISTINCT FROM OLD.{ledger.serving_floor_column}
               OR (
                   OLD.{ledger.digest_column} IS NOT NULL
                   AND NEW.{ledger.digest_column}
                       IS DISTINCT FROM OLD.{ledger.digest_column}
               )
            THEN
                RAISE EXCEPTION '{_IMMUTABLE_MEMBERSHIP_MESSAGE}';
            END IF;
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
    conn.execute(f"DROP TRIGGER IF EXISTS {name}_update ON {ledger.table}")
    conn.execute(
        f"CREATE TRIGGER {name}_update BEFORE UPDATE OF {ledger.entry_column}, "
        f"{ledger.digest_column}, {ledger.serving_floor_column} "
        f"ON {ledger.table} FOR EACH ROW EXECUTE FUNCTION {function_name}()"
    )
    conn.execute(f"DROP TRIGGER IF EXISTS {name}_delete ON {ledger.table}")
    conn.execute(
        f"CREATE TRIGGER {name}_delete BEFORE DELETE ON {ledger.table} "
        f"FOR EACH ROW EXECUTE FUNCTION {function_name}()"
    )


def adoption_transition_guard_is_enforced(
    conn: Any,
    ledger: LedgerContract,
    evidence: AdoptionEvidenceContract,
) -> bool:
    """Return whether the exact declared transition guard is active."""
    name = _guard_object_name(ledger, evidence)
    if not db_backend.connection_is_postgres(conn):
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
            "AND tbl_name = ?",
            (ledger.table,),
        ).fetchall()
        actual = {str(row[0]): _normalized_sql(row[1]) for row in rows}
        expected = {
            f"{name}_update": _sqlite_update_guard_sql(name, ledger, evidence),
            f"{name}_adopt": _sqlite_adoption_guard_sql(name, ledger, evidence),
            f"{name}_delete": _sqlite_delete_guard_sql(name, ledger),
        }
        return all(
            actual.get(trigger) == _normalized_sql(definition)
            for trigger, definition in expected.items()
        )

    rows = conn.execute(
        "SELECT trigger.tgname, procedure.proname, trigger.tgenabled, "
        "trigger.tgtype::int, "
        "procedure.prosrc, language.lanname, "
        "pg_catalog.pg_get_function_result(procedure.oid), "
        "trigger.tgattr::text "
        "FROM pg_trigger AS trigger "
        "JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid "
        "JOIN pg_language AS language ON language.oid = procedure.prolang "
        "WHERE trigger.tgrelid = to_regclass(%s) "
        "AND trigger.tgname IN (%s, %s) AND NOT trigger.tgisinternal",
        (ledger.table, f"{name}_update", f"{name}_delete"),
    ).fetchall()
    if len(rows) != 2:
        return False
    attributes = conn.execute(
        "SELECT attname, attnum::text FROM pg_attribute "
        "WHERE attrelid = to_regclass(%s) AND attname IN (%s, %s, %s)",
        (
            ledger.table,
            ledger.entry_column,
            ledger.digest_column,
            ledger.serving_floor_column,
        ),
    ).fetchall()
    by_attribute = {str(row[0]): str(row[1]) for row in attributes}
    expected_attributes = " ".join(
        by_attribute.get(column, "")
        for column in (
            ledger.entry_column,
            ledger.digest_column,
            ledger.serving_floor_column,
        )
    )
    function_name = adoption_transition_guard_function_name(ledger, evidence)
    expected_body = _normalized_sql(
        f"""
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION '{_IMMUTABLE_MEMBERSHIP_MESSAGE}';
            END IF;
            IF NEW.{ledger.entry_column} IS DISTINCT FROM OLD.{ledger.entry_column}
               OR NEW.{ledger.serving_floor_column}
                  IS DISTINCT FROM OLD.{ledger.serving_floor_column}
               OR (
                   OLD.{ledger.digest_column} IS NOT NULL
                   AND NEW.{ledger.digest_column}
                       IS DISTINCT FROM OLD.{ledger.digest_column}
               )
            THEN
                RAISE EXCEPTION '{_IMMUTABLE_MEMBERSHIP_MESSAGE}';
            END IF;
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
    by_name = {str(row[0]): row for row in rows}
    update = by_name.get(f"{name}_update")
    delete = by_name.get(f"{name}_delete")
    return all(
        row is not None
        and str(row[1]) == function_name
        and str(row[2]) == "O"
        and int(row[3]) == trigger_type
        and _normalized_sql(row[4]) == expected_body
        and str(row[5]) == "plpgsql"
        and str(row[6]) == "trigger"
        and str(row[7]).strip() == expected_columns
        for row, trigger_type, expected_columns in (
            (update, 19, expected_attributes),
            (delete, 11, ""),
        )
    )


def _normalized_sql(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().rstrip(";").casefold()


__all__ = [
    "ADOPTION_TRANSITION_GUARD_PREFIX",
    "adoption_transition_guard_function_name",
    "adoption_transition_guard_is_enforced",
    "ensure_adoption_transition_guard",
]

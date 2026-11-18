"""Move project-owned Test Machines and their receipts into the universe."""

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema
from yoke_core.domain.schema_common import _column_exists


MINIMUM_SERVING_VERSION = "next-release"

_LEGACY_PREFIX = "test-machine:"
_LEGACY_PATTERN = "test-machine:%"
_RECEIPTS = (
    (
        "test_machine_verifications",
        "status, checked_at, receipt_json, error_code, updated_at",
    ),
    (
        "test_machine_operation_receipts",
        "operation, status, performed_at, receipt_json, error_code, "
        "lease_id, contract_digest, updated_at",
    ),
)


def apply(conn):
    """Preserve settings verbatim and transfer the receipt foreign keys."""
    p = "%s" if connection_is_postgres(conn) else "?"
    duplicates = conn.execute(
        f"SELECT type FROM project_capabilities WHERE type LIKE {p} "
        "GROUP BY type HAVING COUNT(*) > 1 ORDER BY type",
        (_LEGACY_PATTERN,),
    ).fetchall()
    if duplicates:
        names = ", ".join(row[0][len(_LEGACY_PREFIX):] for row in duplicates)
        raise ValueError(
            f"duplicate Test Machine names: {names}; resolve duplicate "
            "registrations through a reviewed data repair before retrying the migration"
        )

    legacy = []
    for table, columns in _RECEIPTS:
        if _column_exists(conn, table, "project_id"):
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}_legacy")
            legacy.append((table, columns))

    ensure_test_machine_schema(conn, commit=False)
    conn.execute(
        f"INSERT INTO test_machines (name, settings, power_project_id, verified_at, created_at) "
        f"SELECT SUBSTR(type, {len(_LEGACY_PREFIX) + 1}), settings, project_id, verified_at, created_at "
        f"FROM project_capabilities WHERE type LIKE {p}",
        (_LEGACY_PATTERN,),
    )

    for table, columns in legacy:
        receipt_columns = ", ".join(f"legacy.{column}" for column in columns.split(", "))
        conn.execute(
            f"INSERT INTO {table} (test_machine_id, {columns}) "
            f"SELECT machine.id, {receipt_columns} FROM {table}_legacy legacy "
            f"JOIN test_machines machine ON machine.name = SUBSTR(legacy.capability_type, {len(_LEGACY_PREFIX) + 1}) "
            "AND machine.power_project_id = legacy.project_id"
        )
        before = conn.execute(f"SELECT COUNT(*) FROM {table}_legacy").fetchone()[0]
        after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if before != after:
            raise ValueError(
                f"{table} cutover matched {after} of {before} receipts; "
                "repair legacy receipt ownership before retrying the migration"
            )
        conn.execute(f"DROP TABLE {table}_legacy")

    conn.execute(f"DELETE FROM project_capabilities WHERE type LIKE {p}", (_LEGACY_PATTERN,))
    conn.execute(
        f"DELETE FROM capability_secrets WHERE type={p} AND key={p}",
        ("test-machine:windows-native-lab", "admin_password"),
    )


def invariants(conn):
    p = "%s" if connection_is_postgres(conn) else "?"
    for table, _ in _RECEIPTS:
        assert _column_exists(conn, table, "test_machine_id"), f"{table} has legacy keys"
    assert not conn.execute(
        f"SELECT 1 FROM project_capabilities WHERE type LIKE {p}", (_LEGACY_PATTERN,)
    ).fetchone(), "legacy Test Machine capability rows remain"

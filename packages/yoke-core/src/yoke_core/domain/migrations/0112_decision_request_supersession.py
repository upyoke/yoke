"""Keep replaced questions as linked history, including their recorded answers."""

from psycopg import sql

from yoke_core.domain.schema_common import _column_exists


def apply(conn):
    if not _column_exists(conn, "decision_requests", "superseded_by_request_id"):
        conn.execute(
            "ALTER TABLE decision_requests ADD COLUMN superseded_by_request_id "
            "INTEGER REFERENCES decision_requests(id)"
        )
    # Match the status-only CHECK by its column, including databases whose
    # bootstrap chose a different constraint name. Other CHECKs stay intact.
    constraints = conn.execute(
        "SELECT c.conname FROM pg_constraint c JOIN pg_attribute a "
        "ON a.attrelid=c.conrelid AND c.conkey=ARRAY[a.attnum] "
        "WHERE c.conrelid='decision_requests'::regclass "
        "AND c.contype='c' AND a.attname='status'"
    ).fetchall()
    for (name,) in constraints:
        conn.execute(
            sql.SQL("ALTER TABLE decision_requests DROP CONSTRAINT {}").format(
                sql.Identifier(name)
            )
        )
    conn.execute(
        "ALTER TABLE decision_requests ADD CONSTRAINT decision_requests_status_check "
        "CHECK(status IN ('pending', 'resolved', 'withdrawn', 'superseded'))"
    )


def invariants(conn):
    assert _column_exists(conn, "decision_requests", "superseded_by_request_id")
    definitions = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='decision_requests'::regclass AND contype='c'"
    ).fetchall()
    assert any("superseded" in definition for (definition,) in definitions)

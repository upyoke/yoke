"""Boot convergence adds fail-closed replay scope to legacy ledgers."""

from pathlib import Path

from yoke_core.domain import schema
from yoke_core.domain.schema_common import _get_columns
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def test_legacy_ledger_gains_empty_unverifiable_scope_columns(
    tmp_path: Path,
) -> None:
    with init_test_db(tmp_path) as db_path:
        with connect_test_db(db_path) as conn:
            for column in ("actor_id", "authorization_scope", "payload_checksum"):
                conn.execute(f"ALTER TABLE function_call_ledger DROP COLUMN {column}")
            conn.execute(
                "INSERT INTO function_call_ledger "
                "(request_id, function_id, result, created_at) VALUES "
                "('legacy', 'items.scalar.set', '{}', '2026-01-01T00:00:00Z')"
            )
            conn.commit()

        schema.cmd_init()

        with connect_test_db(db_path) as conn:
            columns = _get_columns(conn, "function_call_ledger")
            row = conn.execute(
                "SELECT actor_id, authorization_scope, payload_checksum "
                "FROM function_call_ledger WHERE request_id='legacy'"
            ).fetchone()

    assert {"actor_id", "authorization_scope", "payload_checksum"}.issubset(columns)
    assert row == ("", "", "")

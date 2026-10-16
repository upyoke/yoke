"""Prove token-receipt cleanup is a no-op on an already scrubbed copy."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib
import io
import json
import os
from pathlib import Path

from yoke_contracts.timestamps import temporal_wire
from yoke_core.domain import db_backend
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
from yoke_core.domain.schema_common import _table_exists


ENTRY_NAME = "0078_scrub_admission_secret_receipts"
ZERO_COUNTS = (
    "admission_secret_receipts ledger_rows_rewritten=0 event_envelopes_rewritten=0\n"
)


def _fingerprint(conn, table, identity):
    digest = hashlib.sha256()
    count = 0
    if not _table_exists(conn, table):
        return count, digest.digest()
    # Server cursors bound memory even when a copied telemetry table is large.
    cursor = (
        conn.cursor(name=f"secret_receipt_{table}")
        if db_backend.connection_is_postgres(conn) else conn.cursor()
    )
    try:
        cursor.execute(f"SELECT * FROM {table} ORDER BY {identity}")
        while rows := cursor.fetchmany(500):
            for row in rows:
                encoded = json.dumps(
                    temporal_wire(list(row)), sort_keys=True, separators=(",", ":"),
                ).encode()
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
                count += 1
    finally:
        cursor.close()
    return count, digest.digest()


def _receipts(conn):
    return (
        _fingerprint(conn, "function_call_ledger", "request_id"),
        _fingerprint(conn, "events", "id"),
    )


def verify_secret_receipt_replay(conn) -> str | None:
    """Use the caller's copy and transaction; return a secret-free refusal."""
    output, errors = io.StringIO(), io.StringIO()
    try:
        entry = importlib.import_module(f"yoke_core.domain.migrations.{ENTRY_NAME}")
        with redirect_stdout(output), redirect_stderr(errors):
            entry.invariants(conn)
            before = _receipts(conn)
            entry.apply(conn)
            entry.invariants(conn)
            after = _receipts(conn)
        if output.getvalue() != ZERO_COUNTS or errors.getvalue():
            return "secret_receipt_replay_failed: expected zero rewrite counts only"
        if before != after:
            return "secret_receipt_replay_failed: receipt bytes or identities changed"
    except Exception:
        return "secret_receipt_replay_failed: copy verification did not complete"
    print(
        "admission_secret_receipts_replay ledger_rows_rewritten=0 "
        f"event_envelopes_rewritten=0 ledger_rows_checked={after[0][0]} "
        f"event_envelopes_checked={after[1][0]}", flush=True,
    )
    return None


def main() -> int:
    """Consume only the explicit target and restore point bound by rehearsal."""
    target = os.environ.get("YOKE_DB", "")
    archive = os.environ.get(RESTORE_POINT_ENV, "")
    if (
        not target or target != os.environ.get("YOKE_PG_DSN")
        or not archive or not Path(archive).is_file() or Path(archive).stat().st_size == 0
    ):
        print("secret_receipt_replay_refused: matching validation bindings and archive required")
        return 1
    try:
        with db_backend.connect_psycopg(target) as conn:
            failure = verify_secret_receipt_replay(conn)
            if failure:
                conn.rollback()
                print(failure)
                return 1
    except Exception:
        print("secret_receipt_replay_failed: validation connection did not complete")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

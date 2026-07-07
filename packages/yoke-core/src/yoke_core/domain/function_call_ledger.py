"""Dispatcher idempotency ledger — exact-match ``request_id`` dedup store.

``function_call_ledger`` is the application-state owner for function-call
idempotency: the ``events`` table is telemetry-only, so replay/collision
decisions read this table instead of scanning ``YokeFunctionCalled``
envelopes. One row per first dispatch of a ``request_id``; the dispatcher
writes the row alongside the ``YokeFunctionCalled`` emission
(:func:`record_call` from ``yoke_function_dispatch_events.emit_called``)
and reads it back on reuse (:func:`lookup_call` from
``yoke_function_dispatch._idempotency_lookup``).

First write wins (``ON CONFLICT (request_id) DO NOTHING``); the
cross-function ``idempotency_key_collision`` decision stays in the
dispatcher, which compares the stored ``function_id`` against the
incoming call. Rows older than :data:`LEDGER_TTL_DAYS` are pruned by the
retention surface (``events_prune.cmd_prune``); after the TTL a reused
``request_id`` dispatches fresh instead of replaying.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

LEDGER_TABLE = "function_call_ledger"

# Replay/dedup window in days. Consumed by the retention prune
# (events_prune.cmd_prune).
LEDGER_TTL_DAYS = 7

# Single DDL source, executed by schema_init_tables.create_core_tables.
FUNCTION_CALL_LEDGER_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
  request_id TEXT PRIMARY KEY,
  function_id TEXT NOT NULL,
  result TEXT, -- → JSONB on Postgres
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_function_call_ledger_created
  ON {LEDGER_TABLE}(created_at)
"""


def serialize_result(result: Dict[str, Any]) -> str:
    """Canonical-JSON form for the stored response result."""
    return json.dumps(dict(result), sort_keys=True, separators=(",", ":"))


def ttl_cutoff_iso(now: Optional[Any] = None) -> str:
    """Return the ISO-8601 UTC cutoff below which ledger rows expire."""
    from datetime import datetime, timedelta, timezone

    base = now or datetime.now(timezone.utc)
    return (base - timedelta(days=LEDGER_TTL_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def record_call(
    request_id: Optional[str],
    function_id: str,
    result: Dict[str, Any],
    *,
    created_at: Optional[str] = None,
    conn: Optional[Any] = None,
) -> bool:
    """Insert one ledger row; first write wins. Returns True when written.

    Calls without a ``request_id`` are not recorded (nothing to replay
    against). With the default own-connection path the write is
    non-fatal — a degraded ledger must not fail the dispatch that
    already committed its primary mutation (same posture as
    ``emit_event``). With a caller-supplied ``conn`` (the governed
    migration seed) the caller owns the transaction and errors
    propagate loudly.
    """
    if not request_id:
        return False
    from yoke_core.domain import db_helpers

    stamp = created_at or db_helpers.iso8601_now()
    sql = (
        f"INSERT INTO {LEDGER_TABLE} "
        "(request_id, function_id, result, created_at) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (request_id) DO NOTHING"
    )
    params = (request_id, function_id, serialize_result(result), stamp)
    if conn is not None:
        return conn.execute(sql, params).rowcount > 0
    # Broad on purpose: connection RESOLUTION failures (e.g. the
    # https-transport env refusing a local Postgres binding) raise plain
    # RuntimeError before any database error class can occur, and the
    # own-connection path is documented non-fatal.
    try:
        own = db_helpers.connect()
        try:
            written = own.execute(sql, params).rowcount > 0
            own.commit()
            return written
        finally:
            own.close()
    except Exception:
        return False


def lookup_call(
    request_id: Optional[str],
) -> Optional[Tuple[Dict[str, Any], str]]:
    """Return ``(stored_result, stored_function_id)`` or ``None``.

    Exact ``request_id`` match. Non-fatal: any database error (including
    a missing table on a not-yet-migrated environment) reads as "no
    prior call", so dispatch proceeds fresh.
    """
    if not request_id:
        return None
    try:
        from yoke_core.domain import db_helpers
    except Exception:
        return None
    # Broad on purpose: connection RESOLUTION failures (https-transport
    # envs raise RuntimeError from connect()) degrade to "no prior call"
    # exactly like a missing table — dispatch proceeds fresh.
    try:
        with db_helpers.connect() as conn:
            row = conn.execute(
                f"SELECT result, function_id FROM {LEDGER_TABLE} "
                "WHERE request_id = %s",
                (request_id,),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    raw, function_id = row[0], row[1]
    try:
        stored = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return stored, str(function_id or "")


def count_expired(conn: Any) -> int:
    """Rows past the TTL window (dry-run reporting for the prune)."""
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, LEDGER_TABLE):
        return 0
    row = conn.execute(
        f"SELECT COUNT(*) FROM {LEDGER_TABLE} WHERE created_at < %s",
        (ttl_cutoff_iso(),),
    ).fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)


def prune_expired(conn: Any) -> int:
    """Delete rows past the TTL window; returns the pruned count.

    The caller (``events_prune.cmd_prune``) owns the connection, the
    commit, and the retention audit fingerprint.
    """
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, LEDGER_TABLE):
        return 0
    return conn.execute(
        f"DELETE FROM {LEDGER_TABLE} WHERE created_at < %s",
        (ttl_cutoff_iso(),),
    ).rowcount


__all__ = [
    "FUNCTION_CALL_LEDGER_CREATE_SQL",
    "LEDGER_TABLE",
    "LEDGER_TTL_DAYS",
    "count_expired",
    "lookup_call",
    "prune_expired",
    "record_call",
    "serialize_result",
    "ttl_cutoff_iso",
]

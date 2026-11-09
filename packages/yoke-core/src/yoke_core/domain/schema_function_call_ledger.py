"""Dispatcher idempotency ledger table declaration."""

LEDGER_TABLE = "function_call_ledger"


# Single DDL source, executed by schema_init_tables.create_core_tables.
FUNCTION_CALL_LEDGER_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
  request_id TEXT PRIMARY KEY,
  function_id TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  authorization_scope TEXT NOT NULL DEFAULT '',
  payload_checksum TEXT NOT NULL DEFAULT '',
  result TEXT, -- → JSONB on Postgres
  created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_function_call_ledger_created
  ON {LEDGER_TABLE}(created_at)
"""

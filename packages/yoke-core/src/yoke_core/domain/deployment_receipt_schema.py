"""Append-only schema for retired deployment definitions and run receipts."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script


FLOW_RECEIPT_TRIGGER = "deployment_flow_receipts_immutable"
RUN_RECEIPT_TRIGGER = "deployment_run_receipts_immutable"
FLOW_RECEIPT_TRUNCATE_TRIGGER = "deployment_flow_receipts_no_truncate"
RUN_RECEIPT_TRUNCATE_TRIGGER = "deployment_run_receipts_no_truncate"
FLOW_RECEIPT_SCHEMA = "yoke.deployment-flow-receipt/v1"
RUN_RECEIPT_SCHEMA = "yoke.deployment-run-receipt/v1"


_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS deployment_flow_receipts (
  flow_id TEXT PRIMARY KEY,
  project_id_snapshot INTEGER NOT NULL,
  project_slug_snapshot TEXT NOT NULL,
  definition_observed_at TEXT NOT NULL,
  receipt_schema TEXT NOT NULL CHECK(receipt_schema = '{FLOW_RECEIPT_SCHEMA}'),
  payload TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
  archived_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deployment_flow_receipts_project
  ON deployment_flow_receipts(project_slug_snapshot, flow_id);

CREATE TABLE IF NOT EXISTS deployment_run_receipts (
  run_id TEXT PRIMARY KEY,
  project_id_snapshot INTEGER NOT NULL,
  project_slug_snapshot TEXT NOT NULL,
  flow_id TEXT NOT NULL,
  target_env TEXT,
  status TEXT NOT NULL,
  run_created_at TEXT NOT NULL,
  receipt_schema TEXT NOT NULL CHECK(receipt_schema = '{RUN_RECEIPT_SCHEMA}'),
  payload TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
  archived_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deployment_run_receipts_project_created
  ON deployment_run_receipts(project_slug_snapshot, run_created_at, run_id);
CREATE INDEX IF NOT EXISTS idx_deployment_run_receipts_flow_status
  ON deployment_run_receipts(flow_id, status, run_created_at, run_id);
"""


_POSTGRES_TRIGGER_SQL = f"""
CREATE OR REPLACE FUNCTION deployment_receipts_immutable_fn()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION '% is append-only; deployment receipts cannot be updated or deleted', TG_TABLE_NAME;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_trigger
    WHERE tgname = '{FLOW_RECEIPT_TRIGGER}' AND NOT tgisinternal
  ) THEN
    CREATE TRIGGER {FLOW_RECEIPT_TRIGGER}
    BEFORE UPDATE OR DELETE ON deployment_flow_receipts
    FOR EACH ROW EXECUTE FUNCTION deployment_receipts_immutable_fn();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_trigger
    WHERE tgname = '{RUN_RECEIPT_TRIGGER}' AND NOT tgisinternal
  ) THEN
    CREATE TRIGGER {RUN_RECEIPT_TRIGGER}
    BEFORE UPDATE OR DELETE ON deployment_run_receipts
    FOR EACH ROW EXECUTE FUNCTION deployment_receipts_immutable_fn();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_trigger
    WHERE tgname = '{FLOW_RECEIPT_TRUNCATE_TRIGGER}' AND NOT tgisinternal
  ) THEN
    CREATE TRIGGER {FLOW_RECEIPT_TRUNCATE_TRIGGER}
    BEFORE TRUNCATE ON deployment_flow_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION deployment_receipts_immutable_fn();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_trigger
    WHERE tgname = '{RUN_RECEIPT_TRUNCATE_TRIGGER}' AND NOT tgisinternal
  ) THEN
    CREATE TRIGGER {RUN_RECEIPT_TRUNCATE_TRIGGER}
    BEFORE TRUNCATE ON deployment_run_receipts
    FOR EACH STATEMENT EXECUTE FUNCTION deployment_receipts_immutable_fn();
  END IF;
END
$$;
"""


_SQLITE_TRIGGER_SQL = f"""
CREATE TRIGGER IF NOT EXISTS {FLOW_RECEIPT_TRIGGER}
BEFORE UPDATE ON deployment_flow_receipts
BEGIN
  SELECT RAISE(ABORT, 'deployment_flow_receipts is append-only');
END;
CREATE TRIGGER IF NOT EXISTS {FLOW_RECEIPT_TRIGGER}_delete
BEFORE DELETE ON deployment_flow_receipts
BEGIN
  SELECT RAISE(ABORT, 'deployment_flow_receipts is append-only');
END;
CREATE TRIGGER IF NOT EXISTS {RUN_RECEIPT_TRIGGER}
BEFORE UPDATE ON deployment_run_receipts
BEGIN
  SELECT RAISE(ABORT, 'deployment_run_receipts is append-only');
END;
CREATE TRIGGER IF NOT EXISTS {RUN_RECEIPT_TRIGGER}_delete
BEFORE DELETE ON deployment_run_receipts
BEGIN
  SELECT RAISE(ABORT, 'deployment_run_receipts is append-only');
END;
"""


def ensure_deployment_receipt_schema(conn: Any) -> None:
    """Converge receipt tables, indexes, and database immutability guards."""
    execute_schema_script(conn, _TABLE_SQL)
    if db_backend.connection_is_postgres(conn):
        conn.execute(_POSTGRES_TRIGGER_SQL)
    else:
        execute_schema_script(conn, _SQLITE_TRIGGER_SQL)


__all__ = [
    "FLOW_RECEIPT_TRIGGER",
    "FLOW_RECEIPT_TRUNCATE_TRIGGER",
    "FLOW_RECEIPT_SCHEMA",
    "RUN_RECEIPT_TRIGGER",
    "RUN_RECEIPT_TRUNCATE_TRIGGER",
    "RUN_RECEIPT_SCHEMA",
    "ensure_deployment_receipt_schema",
]

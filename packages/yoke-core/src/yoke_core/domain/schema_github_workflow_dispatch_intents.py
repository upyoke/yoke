"""GitHub workflow dispatch intent table declaration."""

INTENT_TABLE = "github_workflow_dispatch_intents"

GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {INTENT_TABLE} (
  request_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  actor_id TEXT NOT NULL,
  authorization_scope TEXT NOT NULL,
  payload_checksum TEXT NOT NULL,
  repo TEXT NOT NULL,
  workflow TEXT NOT NULL,
  workflow_ref TEXT NOT NULL,
  inputs TEXT NOT NULL, -- → JSONB on Postgres
  correlation_id TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL CHECK(state IN ('pending', 'completed', 'rejected')),
  workflow_run_id TEXT,
  run_url TEXT,
  html_url TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (request_id, attempt)
);
CREATE INDEX IF NOT EXISTS idx_github_workflow_dispatch_intents_created
  ON {INTENT_TABLE}(created_at)
"""

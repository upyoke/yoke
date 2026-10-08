"""Boot-converged collector rate counters and organization-owned signing key."""

from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


def create_frontend_event_tables(conn):
    _add_column_if_not_exists(conn, "organizations", "events_signing_key", "TEXT")
    execute_schema_script(
        conn,
        """
        CREATE TABLE IF NOT EXISTS frontend_attribution_redemptions (
            org_id INTEGER NOT NULL REFERENCES organizations(id),
            nonce TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (org_id, nonce)
        );
        CREATE INDEX IF NOT EXISTS idx_frontend_attribution_expiry
            ON frontend_attribution_redemptions(expires_at);
        CREATE TABLE IF NOT EXISTS frontend_event_rate_limits (
            client_key TEXT PRIMARY KEY,
            window_start INTEGER NOT NULL,
            request_count INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_frontend_event_rate_window
            ON frontend_event_rate_limits(window_start);
    """,
    )

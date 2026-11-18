"""Persistent universe-wide Test Machine identities and power ownership."""

from yoke_core.domain.schema_init_apply import execute_schema_script


TEST_MACHINES_SQL = """
CREATE TABLE IF NOT EXISTS test_machines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    settings TEXT NOT NULL,
    power_project_id INTEGER REFERENCES projects(id),
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    yoke_started_at TIMESTAMPTZ
)
"""


def ensure_test_machine_registry_schema(conn):
    execute_schema_script(conn, TEST_MACHINES_SQL)

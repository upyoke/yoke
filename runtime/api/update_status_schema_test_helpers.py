"""Backend-aware schema installer for update-status integration tests."""

from yoke_core.domain import db_backend
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.update_status_full_test_schema import _SCHEMA_DDL


def _apply_update_status_schema() -> None:
    """Backend-aware ``apply_schema`` strategy for this family's ``_SCHEMA_DDL``.

    Resolves its connection through the backend factory. Postgres has no
    ``CREATE VIEW IF NOT EXISTS`` (its idempotent form is ``CREATE OR REPLACE
    VIEW``), so the fixture DDL is adjusted before apply.
    """
    ddl = _SCHEMA_DDL.replace(
        "CREATE VIEW IF NOT EXISTS",
        "CREATE OR REPLACE VIEW",
    )
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, ddl)
        from yoke_core.domain.workflow_registry import converge_builtin_workflows
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)
    finally:
        conn.close()

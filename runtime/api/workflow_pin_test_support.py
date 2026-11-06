"""Add a real immutable workflow pin to focused database fixtures."""

from __future__ import annotations
import json
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def install_workflow_pin(conn, *, workflow_id: str = "epic") -> None:
    """Extend a minimal items store; production schemas use normal seeding."""
    runtime = builtin_workflow_runtime(workflow_id)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "CREATE TABLE workflow_versions (id INTEGER PRIMARY KEY, workflow_id TEXT, version INTEGER, definition_json TEXT, definition_digest TEXT)"
    )
    conn.execute(
        f"INSERT INTO workflow_versions VALUES (1,{marker},{marker},{marker},{marker})",
        (
            workflow_id,
            runtime.version,
            json.dumps(runtime.definition),
            runtime.definition_digest,
        ),
    )
    columns = set(_get_columns(conn, "items"))
    if "workflow_id" not in columns:
        conn.execute(
            f"ALTER TABLE items ADD COLUMN workflow_id TEXT DEFAULT '{workflow_id}'"
        )
    if "workflow_version_id" not in columns:
        conn.execute(
            "ALTER TABLE items ADD COLUMN workflow_version_id INTEGER DEFAULT 1"
        )
    conn.execute(
        f"UPDATE items SET workflow_id={marker}, workflow_version_id=1", (workflow_id,)
    )

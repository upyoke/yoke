"""Schema bootstrapping and row-shape primitives for the deployment_runs lane.

Contains:
- ``cmd_init``: idempotent DDL for ``deployment_runs``, ``deployment_run_items``,
  ``deployment_run_qa``, ``deployment_preview_environments`` plus the legacy
  ``env_type`` column add-if-missing.
- Row-shape constants: ``RUN_FIELDS``, ``UPDATABLE_FIELDS``, ``_RUN_SELECT``.
- Window-tolerant readers: ``_run_select``, ``_run_named_columns``.
- Status enums: ``VALID_STATUSES``, ``VALID_QA_STATUSES``, ``VALID_ENV_TYPES``.
- Pipe-delimited formatters: ``_pipe_row``, ``_pipe_rows``.

These primitives are consumed directly by every deployment_runs sibling and by
the thin shim at ``deployment_runs.py``.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.runs import RunStatus
from yoke_core.domain.schema_common import (
    _column_exists,
    environment_reference_column_sql,
)


# ---------------------------------------------------------------------------
# Row-shape constants
# ---------------------------------------------------------------------------

RUN_FIELDS = (
    "id",
    "project",
    "flow",
    "target_tier",
    "target_environment",
    "release_lineage",
    "status",
    "current_stage",
    "created_at",
    "started_at",
    "completed_at",
    "created_by",
    "carried_work",
)

UPDATABLE_FIELDS = ("status", "current_stage", "created_by")

VALID_STATUSES = tuple(s.value for s in RunStatus)

VALID_QA_STATUSES = ("pending", "passed", "failed", "waived")

VALID_ENV_TYPES = ("shared", "adhoc")

_RUN_TABLE = "deployment_runs"

# Pipe-format fields whose live table column may be absent during the
# merge-to-deploy window (additive converge has not yet run on the plane
# the local driver is reading).
_RUN_OPTIONAL_FIELD_COLUMNS = {
    "target_tier": "target_tier",
    "target_environment": "target_environment_id",
    "release_lineage": "release_lineage",
    "current_stage": "current_stage",
    "started_at": "started_at",
    "completed_at": "completed_at",
    "created_by": "created_by",
    "carried_work": "carried_work",
}


def _compose_run_select(
    *,
    target_tier: str,
    target_environment: str,
    release_lineage: str,
    current_stage: str,
    started_at: str,
    completed_at: str,
    created_by: str,
    carried_work: str,
) -> str:
    return (
        "id, COALESCE((SELECT p.slug FROM projects p "
        "WHERE p.id = deployment_runs.project_id), '') AS project, "
        f"flow, {target_tier}, {target_environment}, "
        f"{release_lineage}, "
        f"status, {current_stage}, created_at, "
        f"{started_at}, {completed_at}, "
        f"{created_by}, {carried_work}"
    )


# Standard SELECT fragment for full run rows (COALESCE NULLs to empty strings
# to match the shell pipe-delimited output). Live readers use `_run_select`
# so a declared additive column missing from the plane projects empty.
_RUN_SELECT = _compose_run_select(
    target_tier="COALESCE(target_tier,'')",
    target_environment=(
        "COALESCE((SELECT e.name FROM environments e "
        "WHERE e.id=deployment_runs.target_environment_id),'')"
    ),
    release_lineage="COALESCE(release_lineage,'')",
    current_stage="COALESCE(current_stage,'')",
    started_at="COALESCE(started_at,'')",
    completed_at="COALESCE(completed_at,'')",
    created_by="COALESCE(created_by,'')",
    carried_work="COALESCE(carried_work,'')",
)


def _run_column_sql(
    conn: Any,
    column: str,
    present_sql: str,
    *,
    alias: str | None = None,
) -> str:
    """Return *present_sql* when the live table has *column*, else empty."""
    if _column_exists(conn, _RUN_TABLE, column):
        return present_sql
    return f"'' AS {alias or column}"


def _run_select(conn: Any) -> str:
    """Pipe-format SELECT list, empty for unconverged additive columns."""
    return _compose_run_select(
        target_tier=_run_column_sql(conn, "target_tier", "COALESCE(target_tier,'')"),
        target_environment=_run_column_sql(
            conn,
            "target_environment_id",
            "COALESCE((SELECT e.name FROM environments e "
            "WHERE e.id=deployment_runs.target_environment_id),'')",
        ),
        release_lineage=_run_column_sql(
            conn, "release_lineage", "COALESCE(release_lineage,'')"
        ),
        current_stage=_run_column_sql(
            conn, "current_stage", "COALESCE(current_stage,'')"
        ),
        started_at=_run_column_sql(conn, "started_at", "COALESCE(started_at,'')"),
        completed_at=_run_column_sql(conn, "completed_at", "COALESCE(completed_at,'')"),
        created_by=_run_column_sql(conn, "created_by", "COALESCE(created_by,'')"),
        carried_work=_run_column_sql(conn, "carried_work", "COALESCE(carried_work,'')"),
    )


def _run_named_columns(conn: Any, alias: str = "dr") -> tuple[str, str]:
    """Named-column SELECT list plus optional environments join.

    Callers already join ``projects``. The join fragment is empty when
    ``target_environment_id`` has not converged yet.
    """

    def col(name: str) -> str:
        if _column_exists(conn, _RUN_TABLE, name):
            return f"{alias}.{name}"
        return f"NULL AS {name}"

    if _column_exists(conn, _RUN_TABLE, "target_environment_id"):
        environment = "e.name AS target_environment"
        env_join = f"LEFT JOIN environments e ON e.id = {alias}.target_environment_id"
    else:
        environment = "NULL AS target_environment"
        env_join = ""
    columns = ", ".join(
        (
            f"{alias}.id",
            "p.slug AS project",
            f"{alias}.flow",
            col("target_tier"),
            environment,
            col("release_lineage"),
            f"{alias}.status",
            col("current_stage"),
            f"{alias}.created_at",
            col("started_at"),
            col("completed_at"),
            col("created_by"),
            col("carried_work"),
        )
    )
    return columns, env_join


def _run_field_available(conn: Any, field: str) -> bool:
    """Return whether a ``runs get --field`` physical column is live."""
    column = _RUN_OPTIONAL_FIELD_COLUMNS.get(field)
    if column is None:
        return True
    return _column_exists(conn, _RUN_TABLE, column)


# ---------------------------------------------------------------------------
# Pipe-delimited formatters
# ---------------------------------------------------------------------------


def _pipe_row(row) -> str:
    """Format a DB row as a pipe-delimited string."""
    return "|".join(str(v) for v in row)


def _pipe_rows(rows) -> str:
    """Format a list of sqlite3.Row as pipe-delimited lines."""
    return "\n".join(_pipe_row(r) for r in rows)


# ---------------------------------------------------------------------------
# DDL bootstrap
# ---------------------------------------------------------------------------


def cmd_init(db_path: Optional[str] = None) -> None:
    """Create tables if not exist (idempotent)."""
    conn = connect(db_path)
    try:
        environment_ref = environment_reference_column_sql(conn)
        for statement in (
            f"""
            CREATE TABLE IF NOT EXISTS deployment_runs (
                id TEXT PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                flow TEXT NOT NULL REFERENCES deployment_flows(id),
                target_tier TEXT,
                target_environment_id {environment_ref},
                release_lineage TEXT,
                status TEXT NOT NULL DEFAULT 'created'
                    CHECK(status IN ('created','executing','succeeded','failed','cancelled')),
                current_stage TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                created_by TEXT DEFAULT 'operator',
                carried_work TEXT,  -- → JSONB on Postgres
                CONSTRAINT deployment_runs_target_tier_vocabulary
                    CHECK (target_tier IS NULL
                           OR target_tier IN ('persistent','ephemeral')),
                CONSTRAINT deployment_runs_target_tier_environment
                    CHECK ((target_tier IS NOT NULL
                            AND target_tier = 'persistent')
                           = (target_environment_id IS NOT NULL))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS deployment_run_items (
                run_id TEXT NOT NULL REFERENCES deployment_runs(id),
                item_id INTEGER NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (run_id, item_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS deployment_run_qa (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES deployment_runs(id),
                check_name TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'flow_default',
                blocking INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','passed','failed','waived')),
                updated_at TEXT,
                UNIQUE(run_id, check_name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS deployment_preview_environments (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                env_name TEXT NOT NULL,
                run_id TEXT REFERENCES deployment_runs(id),
                status TEXT NOT NULL DEFAULT 'available'
                    CHECK(status IN ('available','claimed','stale')),
                env_type TEXT NOT NULL DEFAULT 'adhoc'
                    CHECK(env_type IN ('shared','adhoc')),
                url TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, env_name)
            )
            """,
        ):
            conn.execute(statement)
        # Migration: add env_type column if missing (for existing DBs)
        if not _column_exists(conn, "deployment_preview_environments", "env_type"):
            try:
                conn.execute(
                    "ALTER TABLE deployment_preview_environments "
                    "ADD COLUMN env_type TEXT NOT NULL DEFAULT 'adhoc' "
                    "CHECK(env_type IN ('shared','adhoc'))"
                )
                conn.commit()
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()

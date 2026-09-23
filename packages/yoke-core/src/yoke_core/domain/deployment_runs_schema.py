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

from typing import Any

from yoke_core.domain.deployment_run_pipe_format import pipe_row, pipe_rows
from yoke_core.domain.deployment_runs_schema_init import cmd_init as cmd_init
from yoke_core.domain.runs import RunStatus
from yoke_core.domain.schema_common import (
    _column_exists,
)

_pipe_row = pipe_row
_pipe_rows = pipe_rows


# Row-shape constants

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
    "bound_sources",
    "artifact_identity",
    "composition_resolution",
    "composition_frozen_at",
    "requirement_snapshot",
)

# ``release_lineage`` is writable only while a run is still ``created``, so a
# run prepared before its work merged can be bound to the commit that merge
# produced. ``deployment_run_lineage_rebind`` owns that window.
UPDATABLE_FIELDS = (
    "status",
    "current_stage",
    "created_by",
    "release_lineage",
    "artifact_identity",
    "composition_resolution",
)

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
    "bound_sources": "bound_sources",
    "artifact_identity": "artifact_identity",
    "composition_resolution": "composition_resolution",
    "composition_frozen_at": "composition_frozen_at",
    "requirement_snapshot": "requirement_snapshot",
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
    bound_sources: str,
    artifact_identity: str,
    composition_resolution: str,
    composition_frozen_at: str,
    requirement_snapshot: str,
) -> str:
    return (
        "id, COALESCE((SELECT p.slug FROM projects p "
        "WHERE p.id = deployment_runs.project_id), '') AS project, "
        f"flow, {target_tier}, {target_environment}, "
        f"{release_lineage}, "
        f"status, {current_stage}, created_at, "
        f"{started_at}, {completed_at}, "
        f"{created_by}, {carried_work}, {bound_sources}, "
        f"{artifact_identity}, "
        f"{composition_resolution}, {composition_frozen_at}, {requirement_snapshot}"
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
    bound_sources="COALESCE(bound_sources,'')",
    artifact_identity="COALESCE(artifact_identity,'')",
    composition_resolution="COALESCE(composition_resolution,'')",
    composition_frozen_at="COALESCE(composition_frozen_at,'')",
    requirement_snapshot="COALESCE(requirement_snapshot,'')",
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
        bound_sources=_run_column_sql(
            conn, "bound_sources", "COALESCE(bound_sources,'')"
        ),
        artifact_identity=_run_column_sql(
            conn, "artifact_identity", "COALESCE(artifact_identity,'')"
        ),
        composition_resolution=_run_column_sql(
            conn, "composition_resolution", "COALESCE(composition_resolution,'')"
        ),
        composition_frozen_at=_run_column_sql(
            conn, "composition_frozen_at", "COALESCE(composition_frozen_at,'')"
        ),
        requirement_snapshot=_run_column_sql(
            conn, "requirement_snapshot", "COALESCE(requirement_snapshot,'')"
        ),
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
            col("bound_sources"),
            col("artifact_identity"),
            col("composition_resolution"),
            col("composition_frozen_at"),
            col("requirement_snapshot"),
            col("candidate_containment"),
        )
    )
    return columns, env_join


def _run_field_available(conn: Any, field: str) -> bool:
    """Return whether a ``runs get --field`` physical column is live."""
    column = _RUN_OPTIONAL_FIELD_COLUMNS.get(field)
    if column is None:
        return True
    return _column_exists(conn, _RUN_TABLE, column)

"""Current deployment-run row shapes, status values and pipe formatting."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists

from yoke_core.domain.deployment_run_pipe_format import pipe_row, pipe_rows
from yoke_core.domain.runs import RunStatus
from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

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


VALID_ENV_TYPES = ("shared", "adhoc")

_RUN_TABLE = "deployment_runs"
RUN_INSTANT_FIELDS = frozenset(
    column for table, column in STORED_INSTANT_COLUMNS if table == _RUN_TABLE
)

# Full run rows retain native clocks; the pipe formatter owns blank nulls.
_RUN_SELECT = (
    "id, COALESCE((SELECT p.slug FROM projects p "
    "WHERE p.id = deployment_runs.project_id), '') AS project, "
    "flow, COALESCE(target_tier,''), "
    "COALESCE((SELECT e.name FROM environments e "
    "WHERE e.id=deployment_runs.target_environment_id),''), "
    "COALESCE(release_lineage,''), status, COALESCE(current_stage,''), "
    "created_at, started_at, completed_at, COALESCE(created_by,''), "
    "COALESCE(carried_work,''), COALESCE(bound_sources,''), "
    "COALESCE(artifact_identity,''), COALESCE(composition_resolution,''), "
    "composition_frozen_at, COALESCE(requirement_snapshot,'')"
)


def bound_sources_column(alias: str, *, include_preparation_receipt: bool) -> str:
    """Keep source identities without copying driver intake into presentation."""
    column = f"{alias}.bound_sources"
    if include_preparation_receipt:
        return column
    return (
        f"CASE WHEN {column} IS NULL OR {column} = '' "
        f"THEN {column} ELSE ({column}::jsonb "
        "- 'preparation_receipt')::text END AS bound_sources"
    )


def _run_named_columns(
    alias: str = "dr", *, include_preparation_receipt: bool = True
) -> tuple[str, str]:
    """Named-column SELECT list and its environments join; callers join projects."""

    def col(name: str) -> str:
        return f"{alias}.{name}"

    bound_sources = bound_sources_column(
        alias, include_preparation_receipt=include_preparation_receipt
    )

    environment = "e.name AS target_environment"
    env_join = f"LEFT JOIN environments e ON e.id = {alias}.target_environment_id"
    columns = ", ".join(
        (
            f"{alias}.id",
            "p.slug AS project",
            "p.id AS project_id",
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
            bound_sources,
            col("artifact_identity"),
            col("composition_resolution"),
            col("composition_frozen_at"),
            col("requirement_snapshot"),
            col("candidate_containment"),
            col("settling_at"),
            col("membership_removals"),
            col("superseded_by_run_id"),
            col("supersedes_run_id"),
        )
    )
    return columns, env_join


def history_run_columns(conn: Any) -> tuple[str, str]:
    def column(name: str) -> str:
        return f"dr.{name}" if _column_exists(conn, "deployment_runs", name) else "NULL"

    if _column_exists(conn, "deployment_runs", "target_environment_id"):
        environment = "e.name"
        environment_join = (
            " LEFT JOIN environments e ON e.id = dr.target_environment_id"
        )
    else:
        environment = "NULL"
        environment_join = ""
    sources = (
        bound_sources_column("dr", include_preparation_receipt=False)
        if db_backend.connection_is_postgres(conn)
        and _column_exists(conn, "deployment_runs", "bound_sources")
        else f"{column('bound_sources')} AS bound_sources"
    )
    fields = ", ".join(
        (
            "dr.id",
            "dr.project_id",
            "p.slug AS project",
            "dr.flow",
            "df.name AS flow_name",
            f"{column('target_tier')} AS target_tier",
            f"{environment} AS target_environment",
            "dr.status",
            f"{column('current_stage')} AS current_stage",
            "dr.created_at",
            f"{column('started_at')} AS started_at",
            f"{column('completed_at')} AS completed_at",
            f"{column('carried_work')} AS carried_work",
            sources,
            f"{column('candidate_containment')} AS candidate_containment",
            f"{column('membership_removals')} AS membership_removals",
            # The identity a run froze. Without these three scalars a reader
            # cannot tell whether evidence still answers for the run.
            f"{column('release_lineage')} AS release_lineage",
            f"{column('artifact_identity')} AS artifact_identity",
            f"{column('composition_frozen_at')} AS composition_frozen_at",
            "df.stages",
        )
    )
    joins = (
        " FROM deployment_runs dr JOIN projects p ON p.id = dr.project_id "
        "JOIN deployment_flows df ON df.id = dr.flow" + environment_join
    )
    return fields, joins

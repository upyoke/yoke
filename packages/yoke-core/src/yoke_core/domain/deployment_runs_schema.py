"""Current deployment-run row shapes, status values and pipe formatting."""

from __future__ import annotations

from yoke_core.domain.deployment_run_pipe_format import pipe_row, pipe_rows
from yoke_core.domain.deployment_runs_schema_init import cmd_init as cmd_init
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


def _run_named_columns(
    alias: str = "dr", *, include_preparation_receipt: bool = True
) -> tuple[str, str]:
    """Named-column SELECT list and its environments join; callers join projects."""

    def col(name: str) -> str:
        return f"{alias}.{name}"

    bound_sources = col("bound_sources")
    if not include_preparation_receipt:
        # Shipping needs pinned project identities, not the driver's frozen
        # intake receipt. Project it before transferring large rows from SQL.
        bound_sources = (
            f"CASE WHEN {bound_sources} IS NULL OR {bound_sources} = '' "
            f"THEN {bound_sources} ELSE ({bound_sources}::jsonb "
            "- 'preparation_receipt')::text END AS bound_sources"
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

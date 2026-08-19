"""Resolve a deployment run's typed target before creation.

One question, answered once: which tier and which registered environment
does a run of this flow deploy to? Copies the flow's registered target by
default; an operator override names another of the project's environments
and forces the persistent tier.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.project_identity import resolve_project


MIGRATION_APPLY_RECIPE = "python3 -m runtime.api.tools.apply_migration_history"


class EnvironmentRegistryMigrationRequired(ValueError):
    """The flow still stores a pre-registry environment name."""

    code = "environment_registry_migration_required"


def coerce_target_environment_id(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise EnvironmentRegistryMigrationRequired(
            "deployment flow target_environment_id still contains the "
            f"pre-migration environment reference {value!r}; pre-apply the "
            "environment registry migration with "
            f"`{MIGRATION_APPLY_RECIPE}`, then retry"
        ) from None


def cmd_resolve_target(
    project: str,
    flow: str,
    environment_override: Optional[str] = None,
    db_path: Optional[str] = None,
) -> tuple[str, int | None, str]:
    """Resolve an internal key plus the operator-facing environment name."""
    from yoke_core.domain.environment_delivery_record import (
        environment_name,
        require_registered_environment,
    )

    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project)
        assert ident is not None
        if environment_override:
            environment_id = require_registered_environment(
                conn, ident.id, environment_override,
            )
            return (
                "persistent",
                environment_id,
                environment_name(conn, environment_id) or "",
            )
        row = query_one(
            conn,
            "SELECT COALESCE(target_tier, '') AS target_tier, "
            "target_environment_id "
            "FROM deployment_flows WHERE id=%s AND project_id=%s",
            (flow, ident.id),
        )
        if row is None:
            raise LookupError(
                f"unknown deployment flow {flow!r} for project {ident.slug!r}"
            )
        tier = str(row["target_tier"] if hasattr(row, "keys") else row[0])
        raw_environment_id = (
            row["target_environment_id"] if hasattr(row, "keys") else row[1]
        )
        environment_id = coerce_target_environment_id(raw_environment_id)
        return (
            tier,
            environment_id,
            environment_name(conn, environment_id) or "",
        )
    finally:
        conn.close()


__all__ = [
    "EnvironmentRegistryMigrationRequired",
    "MIGRATION_APPLY_RECIPE",
    "cmd_resolve_target",
    "coerce_target_environment_id",
]

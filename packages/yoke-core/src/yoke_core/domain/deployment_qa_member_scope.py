"""The deployment QA scope a delivered member can credit."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.deployment_flow_policy import LEGACY_DEFINITION_SCHEMA_VERSION


def legacy_run_credits_run_wide(conn: Any, *, run_id: str, item_id: int) -> bool:
    """Only a member delivered by a schema-1 run can credit run-wide QA."""
    return bool(
        query_scalar(
            conn,
            "SELECT COUNT(*) FROM deployment_runs dr "
            "JOIN deployment_flows df ON df.id=dr.flow "
            "JOIN deployment_run_items dri ON dri.run_id=dr.id "
            "WHERE dr.id=%s AND dri.item_id=%s AND df.definition_schema_version=%s",
            (str(run_id), int(item_id), LEGACY_DEFINITION_SCHEMA_VERSION),
        )
    )

"""Resolve what a flow definition's stages name against what the project has.

Shape validation asks whether a definition is well formed; this asks whether
the things it names exist for the project authoring it — the environment a
stage deploys to, the capability a preview stage runs on, the reusable QA
plan a stage borrows. Those are questions only the database can answer, and
answering them at definition time is what keeps a flow from failing halfway
through its first run against a name nobody registered.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.project_identity import resolve_project


def validate_stage_references(
    conn: Any,
    *,
    project: str,
    stages_json: str,
) -> None:
    """Require every stage target and reusable QA plan to belong to the project."""
    stages = json.loads(stages_json)
    ident = resolve_project(conn, project)
    assert ident is not None

    for index, stage in enumerate(stages):
        target = stage.get("target") if isinstance(stage, Mapping) else None
        if not isinstance(target, Mapping):
            continue
        kind = target.get("kind")
        if kind == "persistent_environment":
            _require_registered_environment(
                conn, project=project, project_id=ident.id, index=index,
                environment=str(target.get("environment") or ""),
            )
        elif kind == "run_preview":
            capability = target.get("capability")
            if not capability:
                # A source_stage reference chains to an earlier run_preview
                # stage, which was already validated on its own turn through
                # this loop; nothing further to resolve here.
                continue
            _require_registered_capability(
                conn, project=project, project_id=ident.id, index=index,
                capability=str(capability),
            )

    from yoke_core.domain.deployment_requirement_snapshots import (
        validate_flow_plan_references,
    )

    validate_flow_plan_references(conn, project_id=ident.id, stages=stages)


def _require_registered_environment(
    conn: Any, *, project: str, project_id: int, index: int, environment: str
) -> None:
    from yoke_core.domain.environment_reference import resolve

    try:
        resolve(conn, project_id=project_id, name=environment)
    except LookupError as exc:
        raise LookupError(
            f"stage {index} target environment {environment!r} is not "
            f"registered for project {project!r}"
        ) from exc


def _require_registered_capability(
    conn: Any, *, project: str, project_id: int, index: int, capability: str
) -> None:
    has_capability = query_scalar(
        conn,
        "SELECT COUNT(*) FROM project_capabilities "
        "WHERE project_id=%s AND type=%s",
        (project_id, capability),
    )
    if not has_capability:
        raise LookupError(
            f"stage {index} target capability {capability!r} is not "
            f"registered for project {project!r}; register it with: "
            f"yoke projects capability-settings merge --project {project} "
            f"--cap-type {capability} --set <key>=<value>"
        )


__all__ = ["validate_stage_references"]

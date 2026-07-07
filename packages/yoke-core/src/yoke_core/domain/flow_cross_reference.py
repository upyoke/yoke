"""Project cross-reference validation for deployment flow stages.

A ``migration_apply`` stage references a model by name; this module
checks that the referenced model is declared in the project's
``migration_model`` capability and that the model is not already bound
to another ``migration_apply`` stage anywhere in the project's flows.

Stage-shape validation is in :mod:`yoke_core.domain.flow_validation`
and is expected to have already run before any of these checks.
"""
from __future__ import annotations

import json
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.project_identity import ProjectIdentity, resolve_project


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _load_project_migration_models(
    conn, project: str | int | ProjectIdentity
) -> Optional[set]:
    """Return declared model_names for the project, or None if no capability.

    None signals the project has no ``migration_model`` capability; flows
    on such projects may not carry ``migration_apply`` stages.
    """
    ident = project if isinstance(project, ProjectIdentity) else resolve_project(conn, project, required=False)
    if ident is None:
        return None
    p = _p(conn)
    try:
        raw = query_scalar(
            conn,
            "SELECT settings FROM project_capabilities "
            f"WHERE project_id = {p} AND type = 'migration_model'",
            (ident.id,),
        )
    except Exception:
        return None
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    models = parsed.get("models") if isinstance(parsed, dict) else None
    if not isinstance(models, dict):
        return None
    return set(models.keys())


def _validate_flow_stages_cross_reference(
    conn,
    project: str | int,
    stages_json: str,
    flow_id: Optional[str] = None,
) -> None:
    """Cross-reference ``migration_apply`` stages with the project.

    Enforces:
    - model_name resolves to a declared model in the project's
      ``migration_model`` capability.
    - within-flow exclusivity: each model appears in at most one
      ``migration_apply`` stage within a single flow.
    - per-project cross-flow uniqueness: a given model appears in at
      most one ``migration_apply`` stage across all of the project's
      ``deployment_flows`` rows. When ``flow_id`` is
      given and matches an existing row, that row is excluded so the
      caller can save updates to the same flow.

    Structural validation is expected to have already run via
    :func:`yoke_core.domain.flow_validation.validate_stages`.
    """
    try:
        stages = json.loads(stages_json)
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(stages, list):
        return
    migration_apply_stages = [
        (i, s) for i, s in enumerate(stages)
        if isinstance(s, dict) and s.get("kind") == "migration_apply"
    ]
    if not migration_apply_stages:
        return

    ident = resolve_project(conn, project)
    assert ident is not None
    project_label = ident.slug
    declared_models = _load_project_migration_models(conn, ident)

    for i, stage in migration_apply_stages:
        model_name = stage.get("model_name")
        if declared_models is None:
            raise ValueError(
                f'stage {i} (kind=migration_apply) references model '
                f'"{model_name}" but project "{project_label}" has no '
                f'migration_model capability declared'
            )
        if model_name not in declared_models:
            raise ValueError(
                f'stage {i} (kind=migration_apply) references undeclared '
                f'model "{model_name}" for project "{project_label}" '
                f'(declared: {sorted(declared_models)})'
            )

    seen_in_flow = {}
    for i, stage in migration_apply_stages:
        model_name = stage["model_name"]
        if model_name in seen_in_flow:
            raise ValueError(
                f'migration_apply stages for model "{model_name}" appear '
                f'more than once in the same flow '
                f'(stages {seen_in_flow[model_name]} and {i}); '
                f'each model must appear in at most one migration_apply '
                f'stage within a flow'
            )
        seen_in_flow[model_name] = i

    ident = resolve_project(conn, project, required=False)
    if ident is None:
        raise ValueError(f'project "{project}" does not exist')
    p = _p(conn)

    rows = query_rows(
        conn,
        f"SELECT id, stages FROM deployment_flows WHERE project_id = {p}",
        (ident.id,),
    )
    for row in rows:
        existing_flow_id = row[0]
        if flow_id is not None and existing_flow_id == flow_id:
            continue
        try:
            existing_stages = json.loads(row[1])
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if not isinstance(existing_stages, list):
            continue
        for es in existing_stages:
            if not isinstance(es, dict) or es.get("kind") != "migration_apply":
                continue
            existing_model = es.get("model_name")
            if existing_model in seen_in_flow:
                raise ValueError(
                    f'model "{existing_model}" already has a migration_apply '
                    f'stage in flow "{existing_flow_id}" for project '
                    f'"{project_label}"; each model must appear in at most one '
                    f'migration_apply stage across all of the project\'s '
                    f'deployment_flows rows'
                )

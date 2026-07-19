"""Serializable snapshot of the project renderer settings.

The aggregate Pulumi settings endpoint (``GET /v1/projects/{project}/
pulumi-stack-config``) serves this secret-free snapshot for bounded project
authority checks that do not need an exact stack program. Exact stack execution
uses the stack-scoped no-store endpoint and project-owned Pack source. The
snapshot is the full :class:`~yoke_core.domain.project_renderer_settings
.ProjectRendererSettings` value (verified secret-free: hosts, stack
names, instance sizing, state-bucket/KMS aliases, and the KMS-encrypted
Pulumi data key, which is ciphertext by design).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
    _load_project_renderer_settings,
    select_primary_environment,
)

# Version tag for the stack-config payload (request and response).
STACK_CONFIG_SCHEMA = 1


class ProjectNotFoundError(LookupError):
    """Raised when the requested project does not resolve."""


def snapshot_from_settings(settings: ProjectRendererSettings) -> Dict[str, Any]:
    """Project a settings value into its JSON-serializable snapshot."""
    return {
        "project": settings.project,
        "deploy_namespace": settings.deploy_namespace,
        "display_name": settings.display_name,
        "site_id": settings.site_id,
        "site_settings": settings.site_settings,
        "environments": [
            {"id": env.id, "name": env.name, "settings": env.settings}
            for env in settings.environments
        ],
        "capabilities": settings.capabilities,
    }


def settings_from_snapshot(snapshot: Mapping[str, Any]) -> ProjectRendererSettings:
    """Hydrate a settings value from its snapshot dict.

    Raises :class:`ValueError` on a malformed snapshot so the renderer
    fails loudly instead of rendering from a half-shape.
    """
    project = snapshot.get("project")
    if not isinstance(project, str) or not project:
        raise ValueError("renderer settings snapshot is missing the 'project' slug")
    raw_environments = snapshot.get("environments")
    if not isinstance(raw_environments, list):
        raise ValueError("renderer settings snapshot 'environments' must be a list")
    environments = tuple(
        RendererEnvironmentSettings(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or ""),
            settings=dict(raw.get("settings") or {}),
        )
        for raw in raw_environments
        if isinstance(raw, Mapping)
    )
    capabilities = snapshot.get("capabilities")
    site_settings = snapshot.get("site_settings")
    return ProjectRendererSettings(
        project=project,
        deploy_namespace=str(snapshot.get("deploy_namespace") or project),
        display_name=str(snapshot.get("display_name") or project),
        site_id=str(snapshot.get("site_id") or ""),
        site_settings=dict(site_settings) if isinstance(site_settings, Mapping) else {},
        primary_environment=select_primary_environment(environments),
        environments=environments,
        capabilities=(
            {str(k): dict(v) for k, v in capabilities.items() if isinstance(v, Mapping)}
            if isinstance(capabilities, Mapping)
            else {}
        ),
    )


def build_pulumi_stack_config(conn: Any, project: str) -> Dict[str, Any]:
    """Build the stack-config payload the endpoint serves.

    The payload wraps the renderer settings snapshot in a versioned envelope
    consumed verbatim by bounded project-authority clients.
    """
    ident = resolve_project(conn, project, required=False)
    if ident is None:
        raise ProjectNotFoundError(f"project {project!r} not found")
    settings = _load_project_renderer_settings(conn, ident.slug)
    return {
        "config_schema": STACK_CONFIG_SCHEMA,
        "project_id": ident.id,
        "project_slug": ident.slug,
        "renderer_settings": snapshot_from_settings(settings),
    }


def settings_from_stack_config(payload: Mapping[str, Any]) -> ProjectRendererSettings:
    """Hydrate renderer settings from a stack-config envelope.

    Accepts exactly the body served by the pulumi-stack-config endpoint.
    """
    schema = payload.get("config_schema")
    if schema != STACK_CONFIG_SCHEMA:
        raise ValueError(
            f"stack config schema {schema!r} is not supported "
            f"(renderer speaks {STACK_CONFIG_SCHEMA})"
        )
    snapshot = payload.get("renderer_settings")
    if not isinstance(snapshot, Mapping):
        raise ValueError(
            "stack config payload is missing the 'renderer_settings' snapshot"
        )
    return settings_from_snapshot(snapshot)


__all__ = [
    "STACK_CONFIG_SCHEMA",
    "ProjectNotFoundError",
    "build_pulumi_stack_config",
    "settings_from_snapshot",
    "settings_from_stack_config",
    "snapshot_from_settings",
]

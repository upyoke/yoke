"""Rendering + tracking helpers for the ephemeral-deploy step runner.

Owns the template-to-payload half of :mod:`deploy_ephemeral`: rendered
routing/cleanup/compose content for one preview slug, and the
``ephemeral_environments`` tracking writes.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.pack_render import render_pack_text
from yoke_core.domain.ephemeral_substrate import (
    EphemeralPolicy,
    compose_project_name,
)


class EphemeralDeployError(RuntimeError):
    """Ephemeral deploy failed before/around remote convergence."""


def render_webapp_template(project_root: Path, relative: str, values: dict) -> str:
    """Render one project-owned file installed by the ephemeral Pack."""

    template = project_root
    for part in relative.split("/"):
        template = template / part
    if not template.is_file():
        raise EphemeralDeployError(
            f"[ephemeral] project-owned Pack file missing: {template}"
        )
    return render_pack_text(template.read_text(), values)


def routing_values(policy: EphemeralPolicy) -> dict:
    """Template values for the wildcard routing + cleanup renders.

    Every value describes the source project's preview namespace, regardless
    of which project's environment supplies the physical host.
    """
    return {
        "preview_namespace": policy.preview_namespace,
        "preview_router_name": "".join(
            char if char.isalnum() or char == "_" else "_"
            for char in policy.preview_namespace
        ),
        "preview_domain": policy.preview_domain,
        "preview_route_port_base": str(policy.api_base_port),
        "preview_port_range": str(policy.port_range),
        "preview_ttl_hours": str(policy.ttl_hours),
    }


def slug_files(
    policy: EphemeralPolicy,
    env: DeployEnvironment,
    slug: str,
    image_ref: str,
    api_port: int,
    db_password: str,
    *,
    project_root: Path,
) -> tuple:
    """Render (compose_yaml, env_file, dsn) for one preview slug.

    The DSN rides its own file (``YOKE_PG_DSN_FILE``); the env file
    carries only hex-safe values because docker compose interpolates
    ``$`` inside env files.
    """
    database = policy.preview_namespace.replace("-", "_")
    user = policy.preview_namespace.replace("-", "_")
    compose_yaml = render_webapp_template(
        project_root,
        "ops/core-service/docker-compose.ephemeral.yml.tmpl",
        {
            "project": policy.project,
            "slug": slug,
            "compose_project": compose_project_name(policy.preview_namespace, slug),
            "image_ref": image_ref,
            "api_port": str(api_port),
            "container_port": str(env.api_port),
            "database_name": database,
            "database_user": user,
        },
    )
    env_file = (
        "YOKE_PG_DSN_FILE=/run/yoke/dsn\n"
        f"YOKE_ENVIRONMENT=ephemeral-{slug}\n"
        f"EPHEMERAL_DB_PASSWORD={db_password}\n"
    )
    dsn = f"host=db port=5432 dbname={database} user={user} password={db_password}"
    return compose_yaml, env_file, dsn


def track(project: str, branch: str, updates: dict, item_label: str = "") -> None:
    """Create/update the preview's ``ephemeral_environments`` row."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    created = call_dispatcher(
        function_id="ephemeral_env.create",
        target=TargetRef(kind="global"),
        payload={"project": project, "branch": branch, "item": item_label},
    )
    if not created.success:
        detail = created.error.message if created.error else "request failed"
        raise EphemeralDeployError(f"[ephemeral] tracking create failed: {detail}")
    env_id = int((created.result or {}).get("env_id") or 0)
    if env_id <= 0:
        raise EphemeralDeployError(
            "[ephemeral] tracking create returned no environment id"
        )
    for field, value in updates.items():
        updated = call_dispatcher(
            function_id="ephemeral_env.update",
            target=TargetRef(kind="global"),
            payload={"env_id": env_id, "field": field, "value": str(value)},
        )
        if not updated.success:
            detail = updated.error.message if updated.error else "request failed"
            raise EphemeralDeployError(
                f"[ephemeral] tracking update {field} failed: {detail}"
            )


def emit_ephemeral_event(
    name: str, policy: EphemeralPolicy, slug: str, context: dict
) -> None:
    """Record through the canonical emitter (best-effort)."""
    from yoke_core.domain.deploy_pipeline_events import emit_deployment_event

    emit_deployment_event(
        name,
        event_kind="lifecycle",
        event_type="deployment_run",
        source_type="system",
        severity="STATUS",
        project=policy.project,
        outcome="completed",
        environment=f"ephemeral-{slug}",
        context=context,
    )

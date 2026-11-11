"""Build small project-settings snapshots for value-builder unit tests."""

from __future__ import annotations

from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


def _settings_from_context(
    project: str,
    context: dict | None = None,
    base: dict | None = None,
) -> ProjectRendererSettings:
    """Return a one-environment snapshot holding only runtime-read settings."""
    del context
    base = base or {}
    site_settings = {
        "domains": [{
            "domain_name": base.get("domain_name", ""),
            "dns_provider": base.get("dns_provider", "route53"),
        }],
        "cdn": {"distribution_id": base.get("cloudfront_id", "")},
    }
    env_settings = {
        "hosts": {"origin": base.get("origin_host", "")},
        "servers": [{"host": base.get("origin_ip", "")}],
    }
    capabilities = {
        "aws-admin": {
            "region": base.get("aws_region", "us-east-1"),
            "account_id": base.get("aws_account_id", ""),
        },
        "ssh": {"default_user": base.get("ssh_user", "")},
        "webapp-runtime": {
            "web_port": base.get("web_port", ""),
            "api_port": base.get("api_port", ""),
        },
        "health-endpoint": {
            "health_path": base.get("web_health_path", ""),
            "smoke_paths": base.get("web_smoke_paths", ""),
        },
        "ephemeral-env": {
            "ttl_hours": base.get("ephemeral_ttl_hours", ""),
            "web_base_port": base.get("port_base", ""),
            "api_base_port": base.get("api_port_base", ""),
            "port_range": base.get("port_range", ""),
            "preview_domain": base.get("preview_domain", ""),
            "preview_namespace": base.get("preview_namespace", ""),
            "route_base_port": base.get("preview_route_port_base", ""),
            "trigger": base.get("preview_trigger", "github-push"),
        },
    }
    env = RendererEnvironmentSettings(
        id=f"{project}-prod", name="prod", settings=env_settings
    )
    return ProjectRendererSettings(
        project=project,
        deploy_namespace=project,
        display_name=base.get("project_display_name", project.title()),
        site_id=f"{project}-site",
        site_settings=site_settings,
        primary_environment=env,
        environments=(env,),
        capabilities=capabilities,
    )

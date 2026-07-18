"""Value-gathering helpers for the project template renderer.

Resolves the repo root and collects template variables from the DB-backed cloud-runtime
settings homes: ``projects``, ``sites.settings``, ``environments.settings``,
and ``project_capabilities.settings``. The parent module ``project_renderer``
consumes ``gather_values`` from its ``render_project`` orchestrator.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from yoke_core.domain.project_renderer_settings import (  # noqa: F401
    ProjectRendererSettings,
    RendererEnvironmentSettings,
    _first_mapping,
    _stringify,
    load_project_renderer_settings,
    primary_domain,
    primary_environment_settings,
    primary_server,
)


CONFIGURE_AWS_CREDENTIALS_ACTION = (
    "aws-actions/configure-aws-credentials@"
    "517a711dbcd0e402f90c77e7e2f81e849156e31d # v6.2.2"
)


def _resolve_project_root() -> Path:
    """Resolve the repo root via ``git rev-parse --show-toplevel``."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Error: not in a git repository", file=sys.stderr)
        sys.exit(1)
    return Path(result.stdout.strip())


def _json_field(data: Dict[str, Any], field: str) -> str:
    """Extract a field from a dict, returning empty string if missing."""
    val = data.get(field, "")
    return str(val) if val else ""


def _csv(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value if str(item))
    return _stringify(value)


def _cap_settings_query(
    project: str, cap_type: str, script_dir: Path | None = None,
) -> Dict[str, Any]:
    """Query ``project_capabilities.settings`` directly from the DB."""
    del script_dir
    return load_project_renderer_settings(project).capabilities.get(cap_type, {})


def _project_display_name(project: str, script_dir: Path | None = None) -> str:
    """Query the project display name from the projects table."""
    del script_dir
    return load_project_renderer_settings(project).display_name


def _values_from_settings(
    project: str, settings: ProjectRendererSettings,
) -> Dict[str, str]:
    domain_entry = primary_domain(settings)
    site_cdn = _first_mapping(settings.site_settings.get("cdn"))
    env_settings = primary_environment_settings(settings)
    hosts = _first_mapping(env_settings.get("hosts"))
    server = primary_server(settings)

    aws_settings = settings.capabilities.get("aws-admin", {})
    ssh_settings = settings.capabilities.get("ssh", {})
    domain_settings = settings.capabilities.get("domain", {})
    runtime_settings = settings.capabilities.get("webapp-runtime", {})
    health_settings = settings.capabilities.get("health-endpoint", {})
    ephemeral_settings = settings.capabilities.get("ephemeral-env", {})

    project_name = project
    domain_name = _stringify(domain_entry.get("domain_name"))
    origin_host = _stringify(hosts.get("origin"))
    origin_ip = _stringify(server.get("host") or ssh_settings.get("host"), "TODO")
    ssh_user = _stringify(
        ssh_settings.get("default_user") or ssh_settings.get("user"), "TODO"
    )
    cloudfront_id = _stringify(
        site_cdn.get("distribution_id") or domain_settings.get("distribution_id"),
        "TODO",
    )
    cloudfront_domain = _stringify(
        site_cdn.get("distribution_domain")
        or domain_settings.get("distribution_domain"),
        "TODO",
    )

    return {
        "project_display_name": settings.display_name,
        "PROJECT_NAME_UPPER": project_name.upper(),
        "project_description": "",
        "project_name": project_name,
        # Stable AWS-resource naming input (defaults to the project slug). The
        # pulumi stacks name every resource under this, NOT the live project
        # slug, so a re-parent to a differently-named project renames nothing.
        "deploy_namespace": settings.deploy_namespace,
        "cloudfront_domain": cloudfront_domain,
        "cloudfront_id": cloudfront_id,
        "configure_aws_credentials_action": CONFIGURE_AWS_CREDENTIALS_ACTION,
        "certificate_arn": _stringify(domain_entry.get("certificate_arn"), "TODO"),
        "hosted_zone_id": _stringify(domain_entry.get("hosted_zone_id"), "TODO"),
        "aws_account_id": _stringify(aws_settings.get("account_id"), "TODO"),
        "vps_description": _stringify(server.get("description"), "TODO"),
        "domain_name": domain_name,
        "origin_host": origin_host,
        "origin_ip": origin_ip,
        "aws_region": _stringify(aws_settings.get("region"), "us-east-1"),
        "ssh_user": ssh_user,
        "web_port": _stringify(runtime_settings.get("web_port"), "3000"),
        "api_port": _stringify(runtime_settings.get("api_port"), "8000"),
        "ephemeral_ttl_hours": _stringify(
            ephemeral_settings.get("ttl_hours"), "24",
        ),
        "web_health_path": _stringify(health_settings.get("health_path"), "/"),
        "web_smoke_paths": _csv(health_settings.get("smoke_paths")),
        "domain": domain_name,
        "api_port_base": _stringify(
            ephemeral_settings.get("api_base_port"), "9000",
        ),
        "port_base": _stringify(
            ephemeral_settings.get("web_base_port"), "4000",
        ),
        "port_range": _stringify(ephemeral_settings.get("port_range"), "100"),
        "dns_provider": _stringify(
            domain_entry.get("dns_provider"), "digitalocean",
        ),
    }


def gather_values(project: str, project_root: Path) -> Dict[str, str]:
    """Collect all template variables from DB-backed renderer settings."""
    del project_root
    return _values_from_settings(project, load_project_renderer_settings(project))

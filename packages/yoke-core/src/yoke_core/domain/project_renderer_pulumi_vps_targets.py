"""Standalone VPS Pulumi targets declared by deployment environments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
    _first_mapping,
    _stringify,
)


@dataclass(frozen=True)
class PulumiStandaloneVpsTarget:
    """One exact VPS stack plus the environment that owns its inputs."""

    name: str
    environment_id: str
    environment: str
    config: dict[str, str]


def gather_standalone_vps_targets(
    settings: ProjectRendererSettings,
) -> list[PulumiStandaloneVpsTarget]:
    """Project every environment-declared origin VPS into a render target."""
    targets: list[PulumiStandaloneVpsTarget] = []
    by_name: dict[str, PulumiStandaloneVpsTarget] = {}
    for environment in settings.environments:
        target = _target_from_environment(settings, environment)
        if target is None:
            continue
        existing = by_name.get(target.name)
        if existing is not None:
            raise ValueError(
                f"Pulumi standalone VPS stack {target.name!r} is declared by "
                f"multiple environments for project {settings.project!r}: "
                f"{existing.environment!r} and {target.environment!r}"
            )
        by_name[target.name] = target
        targets.append(target)
    return targets


def standalone_vps_template_values(
    target: PulumiStandaloneVpsTarget,
    values: Mapping[str, str],
) -> dict[str, str]:
    """Overlay one target's environment-owned VPS inputs on shared values."""
    result = dict(values)
    result.update(target.config)
    return result


def _target_from_environment(
    settings: ProjectRendererSettings,
    environment: RendererEnvironmentSettings,
) -> PulumiStandaloneVpsTarget | None:
    pulumi = _first_mapping(environment.settings.get("pulumi"))
    name = str(pulumi.get("origin_vps_stack_name") or "").strip()
    if not name:
        return None
    server = _first_mapping(environment.settings.get("servers"))
    config = {
        "vps_instance_type": _required_server_value(
            settings, environment, server, "instance_type"
        ),
        "vps_root_volume_gb": _required_server_value(
            settings, environment, server, "root_volume_gb"
        ),
        "vps_ssh_key_name": _required_server_value(
            settings, environment, server, "aws_key_pair_name"
        ),
        "vps_iam_instance_profile_name": _stringify(
            server.get("iam_instance_profile_name")
        ),
    }
    return PulumiStandaloneVpsTarget(
        name=name,
        environment_id=environment.id,
        environment=environment.name,
        config=config,
    )


def _required_server_value(
    settings: ProjectRendererSettings,
    environment: RendererEnvironmentSettings,
    server: Mapping[str, object],
    key: str,
) -> str:
    value = _stringify(server.get(key)).strip()
    if value:
        return value
    raise ValueError(
        f"Environment {environment.name!r} servers.{key} for "
        f"{settings.project} is required by standalone VPS stack "
        f"{_first_mapping(environment.settings.get('pulumi')).get('origin_vps_stack_name')!r}"
    )


__all__ = [
    "PulumiStandaloneVpsTarget",
    "gather_standalone_vps_targets",
    "standalone_vps_template_values",
]

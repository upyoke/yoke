"""Pulumi stack-type declarations for the project renderer."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .project_renderer_pulumi_context import _read_pulumi_context
from .project_renderer_settings import ProjectRendererSettings

# Default stack set for projects predating the ``stacks`` field: the
# historical full-webapp pair. Keeps existing project renders byte-identical.
_DEFAULT_STACKS = ("infra", "vps")

# Maps a declared stack type to (program module copied verbatim, config
# template rendered with substitution).
STACK_TYPE_SPECS: Dict[str, tuple[str, str]] = {
    "infra": ("webapp_infra_stack.py", "Pulumi.stack.yaml.tmpl"),
    "vps": ("webapp_vps_stack.py", "Pulumi.stack.yaml.tmpl"),
    "domain": ("webapp_domain_stack.py", "Pulumi.domain-stack.yaml.tmpl"),
    "registry": ("webapp_registry_stack.py", "Pulumi.registry-stack.yaml.tmpl"),
    "runner-fleet": (
        "webapp_runner_fleet_stack.py",
        "Pulumi.runner-fleet-stack.yaml.tmpl",
    ),
}


def gather_pulumi_stacks(
    project: str,
    project_root: Path,
    settings: ProjectRendererSettings | None = None,
) -> List[str]:
    """Return the project's declared Pulumi stack types."""
    data = _read_pulumi_context(project, project_root, settings)
    stacks = data.get("stacks")
    if isinstance(stacks, list) and stacks:
        stack_types = [str(s) for s in stacks]
    else:
        stack_types = list(_DEFAULT_STACKS)

    unknown = sorted(set(stack_types) - set(STACK_TYPE_SPECS))
    if unknown:
        valid = ", ".join(sorted(STACK_TYPE_SPECS))
        raise ValueError(
            f"Unknown Pulumi stack type(s) for {project}: "
            f"{', '.join(unknown)}. Expected one or more of: {valid}."
        )
    return stack_types

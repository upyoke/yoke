"""Pulumi stack-type declarations for the project renderer."""

from __future__ import annotations

import re
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

# A declared stack type outside STACK_TYPE_SPECS is project-owned: its program
# and template resolve by naming convention (project_stack_type_files) and its
# template receives only these render keys.
PROJECT_STACK_RENDER_KEYS = frozenset({
    "aws_account_id", "aws_region", "deploy_namespace", "kms_key_alias",
})
# Stack kinds the renderer already owns outside the ``stacks`` declaration.
_RESERVED_STACK_TYPES = frozenset({"environment"})
_STACK_TYPE_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


class ProjectStackFilesMissing(ValueError):
    """A project-declared stack kind lacks its program or config template."""


def is_project_stack_type(stack_type: str) -> bool:
    """Return whether ``stack_type`` is a valid project-declared kind."""
    return (
        stack_type not in STACK_TYPE_SPECS
        and stack_type not in _RESERVED_STACK_TYPES
        and bool(_STACK_TYPE_SLUG.match(stack_type))
    )


def stack_type_files(stack_type: str) -> tuple[str, str]:
    """Return (program module, config template) for one declared stack type.

    A project-declared kind ``foo-bar`` resolves to ``webapp_foo_bar_stack.py``
    and ``Pulumi.foo-bar-stack.yaml.tmpl`` in the project's infra folder.
    """
    if stack_type in STACK_TYPE_SPECS:
        return STACK_TYPE_SPECS[stack_type]
    if not is_project_stack_type(stack_type):
        raise ValueError(f"Pulumi stack type {stack_type!r} is not valid")
    return (
        f"webapp_{stack_type.replace('-', '_')}_stack.py",
        f"Pulumi.{stack_type}-stack.yaml.tmpl",
    )


def require_project_stack_files(
    project_root: Path, stack_type: str, *, program: Path, template: Path
) -> None:
    """Refuse a project-declared stack kind whose files are not in infra/."""
    if stack_type in STACK_TYPE_SPECS:
        return
    missing = [str(path) for path in (program, template) if not path.is_file()]
    if missing:
        raise ProjectStackFilesMissing(
            f"Project-declared Pulumi stack type {stack_type!r} is missing "
            f"{', '.join(missing)}. Add the program and config template to "
            f"{project_root / 'infra'} or remove {stack_type!r} from the "
            "pulumi-state stacks setting."
        )


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

    invalid = sorted(
        stack_type for stack_type in set(stack_types)
        if stack_type not in STACK_TYPE_SPECS
        and not is_project_stack_type(stack_type)
    )
    if invalid:
        raise ValueError(
            f"Invalid Pulumi stack type(s) for {project}: "
            f"{', '.join(invalid)}. Use a built-in type "
            f"({', '.join(sorted(STACK_TYPE_SPECS))}) or a project type named "
            "as a lowercase slug (letters, digits, single hyphens) other than "
            f"{', '.join(sorted(_RESERVED_STACK_TYPES))}; fix the pulumi-state "
            "stacks setting."
        )
    return stack_types


def pulumi_stack_name(
    stack_type: str,
    settings: ProjectRendererSettings,
    values: Dict[str, str],
) -> str:
    """Return the rendered stack name for one declared legacy stack type."""
    stack_key = stack_type.replace("-", "_")
    return (
        values.get(f"pulumi_{stack_key}_stack_name")
        or f"{settings.deploy_namespace}-{stack_type}"
    )

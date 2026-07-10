"""Exact-stack selection for Pulumi project renders."""

from __future__ import annotations

from typing import Sequence

from .project_renderer_pulumi_instances import PulumiStackInstance
from .project_renderer_pulumi_stack_types import pulumi_stack_name
from .project_renderer_settings import ProjectRendererSettings


def select_pulumi_targets(
    selected_stack: str | None,
    stack_types: Sequence[str],
    instances: Sequence[PulumiStackInstance],
    *,
    settings: ProjectRendererSettings,
    values: dict[str, str],
) -> tuple[list[str], list[PulumiStackInstance]]:
    """Select exactly one rendered stack name, or preserve the full render."""
    if selected_stack is None:
        return list(stack_types), list(instances)
    selected_types = [
        stack_type for stack_type in stack_types
        if pulumi_stack_name(stack_type, settings, values) == selected_stack
    ]
    selected_instances = [
        instance for instance in instances if instance.name == selected_stack
    ]
    match_count = len(selected_types) + len(selected_instances)
    if match_count == 0:
        raise ValueError(
            f"Pulumi stack {selected_stack!r} is not declared for "
            f"project {settings.project!r}"
        )
    if match_count > 1:
        raise ValueError(
            f"Pulumi stack {selected_stack!r} matches multiple declarations "
            f"for project {settings.project!r}"
        )
    return selected_types, selected_instances


__all__ = ["select_pulumi_targets"]

"""Resolve Pulumi program and runtime-template files from a project checkout."""

from __future__ import annotations

from pathlib import Path

def pulumi_program_source(project_root: Path, filename: str) -> Path:
    """Return one project-owned Pulumi program file."""

    return project_root / "infra" / filename


def pulumi_generator_source(project_root: Path, filename: str) -> Path:
    """Return one project-owned deferred stack-config template."""

    return project_root / "infra" / filename


__all__ = [
    "pulumi_generator_source",
    "pulumi_program_source",
]

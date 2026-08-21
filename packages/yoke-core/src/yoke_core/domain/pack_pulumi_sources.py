"""Resolve Pulumi program and runtime-template files from a project checkout."""

from __future__ import annotations

from pathlib import Path


#: Project-owned Pulumi program files live in this checkout subdirectory.
PULUMI_PROGRAM_SUBDIRECTORY = "infra"


def pulumi_program_source(project_root: Path, filename: str) -> Path:
    """Return one project-owned Pulumi program file."""

    return project_root / PULUMI_PROGRAM_SUBDIRECTORY / filename


def pulumi_generator_source(project_root: Path, filename: str) -> Path:
    """Return one project-owned deferred stack-config template."""

    return project_root / PULUMI_PROGRAM_SUBDIRECTORY / filename


__all__ = [
    "PULUMI_PROGRAM_SUBDIRECTORY",
    "pulumi_generator_source",
    "pulumi_program_source",
]

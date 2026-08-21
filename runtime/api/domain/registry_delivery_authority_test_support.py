"""Shared fixtures for the delivery-authority tests.

The grant is authored in two places that must agree — the Pack module that
decides a statement's shape and the engine renderer that merges what each
environment stated — so the descriptor, the region, and the account live here
rather than being restated in each test file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)
from runtime.api.domain.webapp_pulumi_test_support import _pack_program_source

#: Resolved from the latest published Pack rather than pinned, so a new Pack
#: version is covered the moment it ships. A pinned path silently left every
#: version after it untested until someone remembered to bump the literal.
PACK_INFRA = _pack_program_source("webapp_registry_delivery_ssm_policy.py").parent
REGION = "us-east-1"
ACCOUNT = "123456789012"

#: One project's complete grant, as an environment would state it.
STATED = {
    "instance_tags": {"project": "example", "role": "origin"},
    "documents": ["AWS-RunShellScript"],
    "artifact_buckets": ["example-artifacts"],
    "artifact_key_prefixes": ["releases/"],
}


def load_pack_module(module_name: str, path: Path | None = None):
    """Import one Pack file by path; Pack source is not on ``sys.path``.

    Registered in ``sys.modules`` before execution because ``dataclasses``
    resolves a class's own module while processing it, and a module that is
    not yet registered resolves to ``None``.
    """
    spec = importlib.util.spec_from_file_location(
        module_name, path or PACK_INFRA / f"{module_name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def environment(name: str, settings: dict) -> RendererEnvironmentSettings:
    return RendererEnvironmentSettings(id=name, name=name, settings=settings)


def settings_for(*environments: RendererEnvironmentSettings) -> ProjectRendererSettings:
    return ProjectRendererSettings(
        project="example",
        deploy_namespace="example",
        display_name="Example",
        site_id="1",
        site_settings={},
        primary_environment=environments[0] if environments else None,
        environments=tuple(environments),
        capabilities={},
    )


__all__ = [
    "ACCOUNT",
    "PACK_INFRA",
    "REGION",
    "STATED",
    "environment",
    "load_pack_module",
    "settings_for",
]

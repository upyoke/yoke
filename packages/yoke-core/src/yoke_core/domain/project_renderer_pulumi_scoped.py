"""Render one Pulumi stack from a schema-v2 scoped config payload."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

from yoke_core.domain.project_renderer import render_template
from yoke_core.domain.project_renderer_pulumi_files import (
    ENVIRONMENT_PROGRAM_FILES,
    REGISTRY_PROGRAM_FILES,
    RUNNER_FLEET_PROGRAM_FILES,
    SHARED_PROGRAM_FILES,
)
from yoke_core.domain.project_renderer_pulumi_stack_config import (
    STACK_CONFIG_SCHEMA,
)
from yoke_core.domain.project_renderer_pulumi_stack_types import STACK_TYPE_SPECS
from yoke_core.domain.pulumi_state_capability import validate_stack_state


def render_scoped_pulumi_config(
    payload: Mapping[str, Any],
    *,
    project_root: Path,
    output_dir: Path,
) -> Path:
    """Render exactly the stack named by one validated schema-v2 payload."""
    project = _required_string(payload, "project_slug")
    stack_name = _required_string(payload, "stack_name")
    stack_kind = _required_string(payload, "stack_kind")
    if payload.get("config_schema") != STACK_CONFIG_SCHEMA:
        raise ValueError("Pulumi stack config schema is not supported")
    raw_values = payload.get("render_values")
    if not isinstance(raw_values, Mapping):
        raise ValueError("Pulumi stack config render_values must be an object")
    values = {str(key): str(value) for key, value in raw_values.items()}
    raw_operator_state = payload.get("operator_state")
    state = validate_stack_state({stack_name: raw_operator_state})[stack_name]

    source = project_root / "templates" / "webapp" / "infra"
    destination = output_dir / "infra"
    if not source.is_dir():
        raise FileNotFoundError(f"Pulumi template directory not found: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    pulumi_yaml = source / "Pulumi.yaml"
    if not pulumi_yaml.is_file():
        raise FileNotFoundError(f"Pulumi project template not found: {pulumi_yaml}")
    (destination / "Pulumi.yaml").write_text(
        render_template(pulumi_yaml.read_text(), values)
    )

    template_name, program_files = _stack_files(stack_kind)
    template = source / template_name
    if not template.is_file():
        raise FileNotFoundError(f"Pulumi stack template not found: {template}")
    rendered = render_template(template.read_text(), values)
    operator_lines = (
        f"secretsprovider: {state['secrets_provider']}\n"
        f"encryptedkey: {state['encrypted_key']}\n"
    )
    stack_path = destination / f"Pulumi.{stack_name}.yaml"
    stack_path.write_text(operator_lines + rendered)
    stack_path.chmod(0o600)
    for name in program_files:
        source_file = source / name
        if source_file.is_file():
            shutil.copyfile(source_file, destination / name)
    return stack_path


def _stack_files(stack_kind: str) -> tuple[str, tuple[str, ...]]:
    files = list(SHARED_PROGRAM_FILES)
    if stack_kind == "environment":
        template_name = "Pulumi.environment-stack.yaml.tmpl"
        files.extend(ENVIRONMENT_PROGRAM_FILES)
    elif stack_kind in STACK_TYPE_SPECS:
        program_file, template_name = STACK_TYPE_SPECS[stack_kind]
        files.append(program_file)
        if stack_kind in {"domain", "infra"}:
            files.append("webapp_dns_records.py")
        if stack_kind == "infra":
            files.append("webapp_distribution_stack.py")
        if stack_kind == "runner-fleet":
            files.extend(RUNNER_FLEET_PROGRAM_FILES)
        if stack_kind == "registry":
            files.extend(REGISTRY_PROGRAM_FILES)
    else:
        raise ValueError(f"unsupported Pulumi stack kind {stack_kind!r}")
    return template_name, tuple(dict.fromkeys(files))


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"Pulumi stack config {key} is required")
    return value


__all__ = ["render_scoped_pulumi_config"]

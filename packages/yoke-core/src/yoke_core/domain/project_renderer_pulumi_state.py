"""Pulumi stack YAML operator-state preservation helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

from .project_renderer_settings import (
    PULUMI_STATE_CAPABILITY_TYPE,
    ProjectRendererSettings,
    _first_mapping,
)


# Top-level YAML keys written by `pulumi stack init --secrets-provider`. They
# own the stack's encryption boundary and must survive template re-renders.
_PULUMI_OPERATOR_STATE_KEYS = ("secretsprovider:", "encryptedkey:")

# Durable settings home for project-level stacks is the ``pulumi-state``
# capability. Environment settings retain environment-stack state.
_PULUMI_STATE_SETTINGS_KEYS = (
    ("secrets_provider", "secretsprovider"),
    ("encrypted_key", "encryptedkey"),
)


def _preserve_operator_state_lines(existing_path: Path) -> str:
    """Read operator-set top-level state lines from an existing stack YAML."""
    if not existing_path.is_file():
        return ""
    preserved: List[str] = []
    for line in existing_path.read_text().splitlines():
        if any(line.startswith(key) for key in _PULUMI_OPERATOR_STATE_KEYS):
            preserved.append(line)
    if not preserved:
        return ""
    return "\n".join(preserved) + "\n"


def _operator_state_lines_from_settings(
    settings: ProjectRendererSettings, stack_name: str,
) -> str:
    """Compose operator state lines from DB-backed Pulumi settings.

    Fresh renders land in per-run scratch dirs, so there is no existing
    stack YAML for :func:`_preserve_operator_state_lines` to read and the
    secrets-provider configuration silently vanishes. Project-level stack
    state lives under the ``pulumi-state`` capability; environment stack state
    lives on the matching environment row.
    """
    capability_state = _first_mapping(
        settings.capabilities.get(PULUMI_STATE_CAPABILITY_TYPE, {}).get(
            "stack_state"
        )
    )
    lines = _state_lines_from_mapping(
        _first_mapping(capability_state.get(stack_name))
    )
    if lines:
        return lines
    for env in settings.environments:
        pulumi = _first_mapping(env.settings.get("pulumi"))
        if pulumi.get("stack_name") != stack_name:
            continue
        return _state_lines_from_mapping(pulumi)
    return ""


def _state_lines_from_mapping(pulumi: Dict[str, object]) -> str:
    lines: List[str] = []
    for settings_key, yaml_key in _PULUMI_STATE_SETTINGS_KEYS:
        value = str(pulumi.get(settings_key) or "").strip()
        if value:
            lines.append(f"{yaml_key}: {value}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _parse_config_values(content: str) -> Dict[str, str]:
    """Map ``namespace:key -> value`` from a stack YAML ``config:`` block."""
    values: Dict[str, str] = {}
    in_config = False
    for line in content.splitlines():
        if not in_config:
            in_config = line.strip() == "config:"
            continue
        if not line.strip():
            continue
        if not line[:1].isspace():
            break
        key, sep, value = line.strip().partition(": ")
        if not (sep or key.endswith(":")):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.rstrip(":").strip()] = value
    return values


def _warn_on_config_divergence(
    project: str, existing_path: Path, rendered_content: str,
) -> List[str]:
    """Warn for existing stack config values that differ from rendered values."""
    if not existing_path.is_file():
        return []
    existing = _parse_config_values(existing_path.read_text())
    rendered = _parse_config_values(rendered_content)
    diverged: List[str] = []
    for key, existing_value in existing.items():
        rendered_value = rendered.get(key)
        if rendered_value is not None and rendered_value != existing_value:
            diverged.append(key)
            print(
                f"WARNING: {existing_path}: config '{key}' will be overwritten "
                f"on re-render (existing={existing_value!r}, "
                f"rendered={rendered_value!r}). Edit "
                f"DB-backed site/environment/capability settings (canonical "
                f"source for Pulumi config) and rerun the intended "
                f"`yoke pulumi exec --project {project} --stack <stack> -- "
                "preview` command.",
                file=sys.stderr,
            )
    return diverged

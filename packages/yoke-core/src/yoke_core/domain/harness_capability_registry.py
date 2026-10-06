"""Shared Yoke command/path capability registry.

Harness manifests describe identity and substrate limitations. They do not own
Yoke workflow or command semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from yoke_contracts.skill_registry import SKILLS, Skill


# The harness universe — every harness Yoke recognises. Used as the default
# `harness_support` value on `OperatorCommand` rows and consumed by the
# capability renderer plus capability-consistency tests so the universe is
# named in exactly one place.
HARNESS_UNIVERSE: tuple[str, ...] = ("claude-code", "codex", "cursor")


@dataclass(frozen=True)
class OperatorCommand:
    """Operator-facing Yoke command metadata."""

    entrypoint: str
    display: str
    reminder: str
    harness_support: tuple[str, ...] = HARNESS_UNIVERSE


def _operator_command(skill: Skill) -> OperatorCommand:
    return OperatorCommand(
        skill.entrypoint, skill.display, f"  {skill.display} -- {skill.description}"
    )


OPERATOR_COMMANDS: tuple[OperatorCommand, ...] = tuple(
    _operator_command(skill) for skill in SKILLS if skill.kind != "internal"
)
DOWNSTREAM_PATHS: tuple[str, ...] = tuple(
    skill.id for skill in SKILLS if skill.kind == "stage"
)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def shared_entrypoints() -> list[str]:
    """Return shared Yoke operator entrypoint ids."""
    return [command.entrypoint for command in OPERATOR_COMMANDS]


def shared_downstream_paths() -> list[str]:
    """Return shared Yoke downstream path ids."""
    return list(DOWNSTREAM_PATHS)


def safe_operator_surface() -> list[OperatorCommand]:
    """Return the full operator command surface entries."""
    return list(OPERATOR_COMMANDS)


def safe_operator_surface_for_harness(harness_id: str) -> list[OperatorCommand]:
    """Return safe operator surface entries supported by the given harness."""
    return [c for c in OPERATOR_COMMANDS if harness_id in c.harness_support]


def safe_operator_surface_entrypoints(harness_id: str) -> list[str]:
    """Return entrypoint ids from the safe operator surface filtered by harness."""
    return [c.entrypoint for c in safe_operator_surface_for_harness(harness_id)]


def manifest_disabled_entrypoints(manifest: Mapping[str, Any]) -> list[str]:
    """Return manifest-declared command limitations."""
    supports = manifest.get("supports", {})
    if not isinstance(supports, Mapping):
        return []
    return _string_list(supports.get("disabled_entrypoints"))


def manifest_disabled_downstream_paths(manifest: Mapping[str, Any]) -> list[str]:
    """Return manifest-declared downstream path limitations."""
    supports = manifest.get("supports", {})
    if not isinstance(supports, Mapping):
        return []
    return _string_list(supports.get("disabled_downstream_paths"))


def entrypoints_for_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Return shared entrypoints after applying manifest limitations."""
    disabled = set(manifest_disabled_entrypoints(manifest))
    return [item for item in shared_entrypoints() if item not in disabled]


def downstream_paths_for_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Return shared downstream paths after applying manifest limitations."""
    disabled = set(manifest_disabled_downstream_paths(manifest))
    return [item for item in shared_downstream_paths() if item not in disabled]


def ordered_commands(entrypoints: Sequence[str]) -> list[OperatorCommand]:
    """Return command metadata in registry order, preserving unknown ids."""
    by_entrypoint = {command.entrypoint: command for command in OPERATOR_COMMANDS}
    known = [
        command for command in OPERATOR_COMMANDS if command.entrypoint in entrypoints
    ]
    extras = [
        OperatorCommand(item, item, f"  {item}")
        for item in entrypoints
        if item not in by_entrypoint
    ]
    return known + extras


def compact_entrypoint_display(entrypoints: Sequence[str] | None = None) -> str:
    """Render a compact command list for startup orientation."""
    return ", ".join(command.display for command in _orientation_commands(entrypoints))


def prompt_reminder_lines(entrypoints: Sequence[str] | None = None) -> list[str]:
    """Render prompt reminder lines for supported entrypoints."""
    return [command.reminder for command in _orientation_commands(entrypoints)]


def _orientation_commands(entrypoints: Sequence[str] | None) -> list[OperatorCommand]:
    if entrypoints is not None:
        return ordered_commands(entrypoints)
    startup = sorted(
        (skill for skill in SKILLS if skill.startup_order is not None),
        key=lambda skill: skill.startup_order,
    )
    return [_operator_command(skill) for skill in startup]

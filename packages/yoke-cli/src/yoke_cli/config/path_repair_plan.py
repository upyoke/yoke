"""Serializable uv shell-setup action for direct fix and onboarding."""

from __future__ import annotations
from typing import Any, Iterable
from yoke_cli.config import path_doctor

UPDATE_SHELL_COMMAND = "uv tool update-shell"


def build(diagnosis: path_doctor.PathDiagnosis) -> dict[str, Any]:
    return {
        "shell": diagnosis.current_shell,
        "tool_bin_dir": diagnosis.tool_bin_dir,
        "directories": [diagnosis.tool_bin_dir],
        "command": UPDATE_SHELL_COMMAND,
        "targets": [{"surface": "shell", "path": UPDATE_SHELL_COMMAND}]
        if diagnosis.needs_fix
        else [],
    }


def required_tools(plan: dict[str, Any]) -> tuple[str, ...]:
    return ("yoke",)


def verification_ok(resolved: Iterable[Any], plan: dict[str, Any]) -> bool:
    return any(row.name == "yoke" and row.path for row in resolved)


def target_description(target: dict[str, Any], plan: dict[str, Any]) -> str:
    return f"Run {UPDATE_SHELL_COMMAND}: uv adds its tool directory to your shell configuration."


def description_lines(plan: dict[str, Any]) -> list[str]:
    return [target_description(target, plan) for target in plan.get("targets", [])]

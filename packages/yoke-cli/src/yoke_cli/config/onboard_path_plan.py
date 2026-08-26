"""Translate a PATH repair plan into onboarding write-plan steps."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import path_repair_plan


PATH_REPAIR_ACTION = "write-shell-path"


def steps(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not plan:
        return []
    return [
        {
            "action": PATH_REPAIR_ACTION,
            "target": str(target.get("path") or ""),
            "surface": str(target.get("surface") or ""),
            "path_repair": plan,
        }
        for target in plan.get("targets", [])
    ]


def friendly_line(step: dict[str, Any]) -> str:
    plan = step.get("path_repair") or {}
    target = {
        "path": step.get("target"),
        "surface": step.get("surface"),
    }
    return path_repair_plan.target_description(target, plan)


__all__ = ["PATH_REPAIR_ACTION", "friendly_line", "steps"]

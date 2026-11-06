"""Pure workflow status membership and display vocabulary for every tier."""

from __future__ import annotations

from typing import Mapping


LEGACY_STATUS_GLYPHS: Mapping[str, str] = {
    "idea": "\U0001f4a1",
    "refining-idea": "📝",
    "refined-idea": "\U0001f48e",
    "planning": "📐",
    "plan-drafted": "📋",
    "refining-plan": "📝",
    "planned": "💎",
    "implementing": "\U0001f528",
    "reviewing-implementation": "\U0001f440",
    "reviewed-implementation": "👍",
    "polishing-implementation": "✨",
    "implemented": "⛳",
    "release": "\U0001f680",
    "done": "✅",
    "blocked": "⛔",
    "stopped": "\U0001f6d1",
    "cancelled": "🚫",
    "failed": "❗",
}
LEGACY_STATUS_BUCKETS: Mapping[str, str] = {
    "done": "done",
    "cancelled": "done",
    "stopped": "blocked",
    "failed": "blocked",
    "release": "release",
    "implemented": "implemented",
    "implementing": "implementing",
    "reviewing-implementation": "reviewing",
    "reviewed-implementation": "reviewing",
    "polishing-implementation": "reviewing",
    "refined-idea": "refined",
    "planned": "refined",
    "refining-idea": "planning",
    "planning": "planning",
    "plan-drafted": "planning",
    "refining-plan": "planning",
    "idea": "idea",
}
"""Renderer fallback for workflow versions published without stage glyphs."""

ENGINE_TERMINAL_STAGE_IDS = frozenset({"cancelled", "stopped"})
ENGINE_WAIT_STAGE_IDS = frozenset({"failed"})
ENGINE_EXCEPTIONAL_STAGE_IDS = ENGINE_TERMINAL_STAGE_IDS | ENGINE_WAIT_STAGE_IDS


def terminal_stage_ids(definition: Mapping) -> frozenset[str]:
    """Successful definition terminals plus engine-owned cancellation terminals."""
    return frozenset(definition["terminal_stage_ids"]) | ENGINE_TERMINAL_STAGE_IDS


def successful_task_stage_ids(definition: Mapping) -> frozenset[str]:
    """Task success starts at the implementation binding's handoff."""
    from yoke_contracts.skill_registry import IMPLEMENTATION_SKILL_IDS

    stages = [str(stage["id"]) for stage in definition["stages"]]
    success = set(definition["terminal_stage_ids"])
    for binding in definition["skill_bindings"]:
        if binding["skill_id"] in IMPLEMENTATION_SKILL_IDS:
            success.update(stages[stages.index(binding["through_stage_id"]) :])
            break
    return frozenset(success)


def terminal_status_sql(definition: str, status: str) -> str:
    """PostgreSQL terminal predicate for a joined workflow definition."""
    engine = ", ".join("'" + value + "'" for value in sorted(ENGINE_TERMINAL_STAGE_IDS))
    return f"({status} IN ({engine}) OR ({definition})::jsonb->'terminal_stage_ids' ? {status})"


def workflow_status_metadata_refusal() -> str:
    """Name the response-field floor and a release-independent recovery."""
    from yoke_contracts.refusal_recovery import compose_refusal

    return compose_refusal(
        "workflow_status_metadata_unavailable: requires the next-release serving floor",
        recovery="Use the installed CLI matching the serving engine until that engine is upgraded",
    )

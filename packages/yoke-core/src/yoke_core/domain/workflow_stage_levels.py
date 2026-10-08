"""Resolve one item's stage level and bounded item override."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Mapping

from yoke_core.domain.item_level_override import (
    LevelOverrideError,
    resolve_level_override,
)
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


class StageLevelError(ValueError):
    """A stage cannot select a launchable level; names its recovery."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_stage_level(
    conn: Any,
    *,
    project_id: int,
    stage: Mapping[str, Any],
    posture: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Shift within the project's ordered levels, then apply both bounds."""
    name = stage.get("level")
    if not name:
        return None
    try:
        resolved = resolve_level_override(
            conn,
            project_id=project_id,
            baseline_level=name,
            override=posture.get("level"),
        )
    except LevelOverrideError as exc:
        raise StageLevelError(
            "stage_level_invalid",
            f"Stage {stage['id']} cannot resolve its effective level: {exc}. "
            "Recovery: correct the item's level posture or publish a workflow "
            "version naming an available project level.",
        ) from exc
    return {
        "stage_id": stage["id"],
        "stage_level": resolved["baseline_level"],
        "stage_glyph": resolved["baseline_glyph"],
        "level": resolved["level"],
        "glyph": resolved["glyph"],
        "override": resolved["override"],
    }


def item_stage_level(
    conn: Any, item_id: int, *, stage_id: str | None = None
) -> dict[str, Any] | None:
    """Read the pinned stage and posture from their existing durable owners."""
    p = placeholder(conn)
    row = conn.execute(
        f"SELECT project_id, status, workflow_posture FROM items WHERE id={p}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        raise StageLevelError(
            "assignment_item_not_found", "Item not found; pass a current item ref."
        )
    runtime = load_item_workflow_runtime(conn, int(item_id))
    current = stage_id or str(row[1])
    if current in runtime.terminal_stage_ids:
        return None
    stage = runtime.stage(current)
    return resolve_stage_level(
        conn,
        project_id=int(row[0]),
        stage=stage or {},
        posture=json.loads(str(row[2] or "{}")),
    )


__all__ = [
    "StageLevelError",
    "default_launch_level",
    "item_stage_level",
    "resolve_stage_level",
]


def default_launch_level(conn: Any, request: Any) -> Any:
    """An explicit level or exact selection wins; otherwise read the live item stage."""
    if request.level or request.executor_surface:
        return request
    from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none
    from yoke_core.domain.session_launch_types import SessionLaunchError

    item_id = (
        resolve_item_ref_or_none(conn, request.item, project=request.project_id)
        if request.item
        else None
    )
    try:
        resolved = item_stage_level(conn, item_id) if item_id is not None else None
    except StageLevelError as exc:
        raise SessionLaunchError(exc.code, str(exc)) from exc
    if resolved is None:
        raise SessionLaunchError(
            "stage_level_missing",
            "Launch has neither an explicit level nor an item stage level. "
            "Recovery: pass --level LEVEL, or ask the control-plane operator to preview and apply `yoke workflows item migrate ITEM --version N --preview` to a compatible version whose live stage declares a level. Existing pins never move automatically.",
        )
    return replace(request, level=resolved["level"])

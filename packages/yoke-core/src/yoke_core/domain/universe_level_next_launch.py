"""Where the next launch at each level goes, answered by the launcher itself.

A launch is placed per project and per caller: only machines serving the
project and reachable by the caller are weighed, and a project may override
the levels. So the Levels page does not predict placement. For every level and
live project it previews the launch the caller would create there, through the
same preview a level launch create runs
(:func:`yoke_core.domain.session_launch_preview_payload.level_preview_payload`).
The preview stores nothing, so the read has no side effects, and its answer is
the launch's answer by construction.

A preview that refuses — no option with capacity, the level undefined in the
project's override, or the caller not an operator there — is reported with
its code and reason rather than dropped.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from yoke_contracts.levels import Level
from yoke_core.domain.session_launch_preview_payload import level_preview_payload
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    SessionLaunchError,
)

Authorize = Callable[[int], LaunchAuthorization]


def _placed(
    project: str, preview: dict[str, Any], display: Callable[[str], str]
) -> dict[str, Any]:
    placement = preview.get("level_placement") or {}
    chosen = placement.get("chosen")
    entry: dict[str, Any] = {
        "project": project,
        "launchable": bool(preview.get("launchable")),
        "code": preview.get("outcome"),
        "reason": preview.get("placement_reason") or placement.get("reason") or "",
    }
    if chosen:
        relay = preview.get("selected_relay") or {}
        entry.update(
            {
                "option_index": chosen["option_index"],
                "fallback": chosen["fallback"],
                "surface": chosen["surface"],
                "model": chosen["model"],
                "display_name": display(chosen["model"]),
                "machine_id": relay.get("machine_id") or chosen["machine_id"],
                "rule": placement.get("rule"),
            }
        )
    return entry


def next_launches(
    conn: Any,
    levels: Sequence[Level],
    projects: Sequence[tuple[int, str]],
    *,
    authorize: Authorize,
    display: Callable[[str], str],
) -> dict[str, list[dict[str, Any]]]:
    """Per level name, each project's previewed next launch at that level."""
    out: dict[str, list[dict[str, Any]]] = {level.name: [] for level in levels}
    for project_id, slug in projects:
        try:
            auth = authorize(project_id)
        except SessionLaunchError as exc:
            refused = {"project": slug, "launchable": False, "code": exc.code}
            for entries in out.values():
                entries.append({**refused, "reason": str(exc)})
            continue
        for level in levels:
            try:
                preview = level_preview_payload(
                    conn, auth=auth, project_id=project_id, level=level.name
                )
            except SessionLaunchError as exc:
                out[level.name].append(
                    {
                        "project": slug,
                        "launchable": False,
                        "code": exc.code,
                        "reason": str(exc),
                    }
                )
                continue
            out[level.name].append(_placed(slug, preview, display))
    return out


__all__ = ["Authorize", "next_launches"]

"""Level capacity and item level overrides, as a steering seat reads them.

A seat launches by level, so the report answers the question that launch
will ask: for each level the project reads, which options can launch right
now, on which machine, with each quota pool's remaining share, headroom and
reset, and where the next launch at that level would go and why. Each level
is a dry run of :func:`session_launch_level_placement.place_level` — the
same weighing ``launch create --level`` performs, under the seat's own
launch authorization — so the report never predicts a placement the launch
would not make. The fleet-wide live worker count per surface beside it is
the count the spread rule reads.

Items the seat is staffing that carry a ``level`` posture override are listed
with it, so a seat can see which launches will not run at the stage level.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from yoke_core.domain.item_level_override import describe_level_override
from yoke_core.domain.machine_registry import display_name
from yoke_core.domain.session_launch_authorization import launch_authorization
from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_level_placement import (
    LevelCandidate,
    LevelPlacement,
    place_level,
)
from yoke_core.domain.session_launch_level_pools import PoolCheck, live_workers
from yoke_core.domain.steering_fleet_plan_capacity import format_reset_utc
from yoke_core.domain.steering_fleet_report_detectors import marker
from yoke_core.domain.universe_levels import effective_levels

LEVELS_HEADING = "levels"
OVERRIDES_HEADING = "item level overrides"


@dataclass(frozen=True)
class LevelReadout:
    """Each level's placement dry run for one scope, and the spread counts."""

    source: str
    live_workers: tuple[tuple[str, int], ...]
    #: ``(glyph, placement)`` per level, lowest first.
    levels: tuple[tuple[str, LevelPlacement], ...]
    #: Why no dry run could be made, when none could.
    unavailable: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "live_workers": dict(self.live_workers),
            "levels": [
                {"glyph": glyph, **placement.to_dict()}
                for glyph, placement in self.levels
            ],
            "unavailable": self.unavailable,
        }


def _session_actor(conn: Any, session_id: str) -> int | None:
    row = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id = {marker(conn)}",
        (session_id,),
    ).fetchone()
    return int(row["actor_id"]) if row and row["actor_id"] is not None else None


def read_level_readout(
    conn: Any, *, project_id: int, session_id: str, now: str
) -> LevelReadout:
    """Dry-run a launch at every level the project reads, as this seat."""
    levels, source = effective_levels(conn, int(project_id))
    workers = tuple(sorted(live_workers(conn).items()))
    actor_id = _session_actor(conn, session_id)
    if actor_id is None:
        return LevelReadout(
            source,
            workers,
            (),
            unavailable=(
                f"session {session_id} carries no actor, so no launch could be "
                "authorized; run `yoke session-control launch preview --level L` "
                "as the seat"
            ),
        )
    auth = launch_authorization(
        conn, actor_id=actor_id, project_id=int(project_id), session_id=session_id
    )
    placements = tuple(
        (
            level.glyph,
            place_level(
                conn,
                auth=auth,
                project_id=int(project_id),
                level=level.name,
                machine_id=None,
                now=now,
                eligibility=derive_launch_eligibility,
            ),
        )
        for level in levels
    )
    return LevelReadout(source, workers, placements)


def read_level_overrides(
    conn: Any, refs: Mapping[int, str]
) -> tuple[tuple[str, str], ...]:
    """``(public_ref, override)`` for each item in ``refs`` that has one."""
    if not refs:
        return ()
    p = marker(conn)
    ids = sorted(refs)
    rows = conn.execute(
        "SELECT id, workflow_posture FROM items "
        f"WHERE id IN ({','.join(p for _ in ids)})",
        ids,
    ).fetchall()
    out: list[tuple[str, str]] = []
    for row in rows:
        raw = row["workflow_posture"]
        posture = json.loads(raw) if isinstance(raw, str) and raw else raw
        text = describe_level_override(posture if isinstance(posture, dict) else {})
        if text:
            out.append((refs[int(row["id"])], text))
    return tuple(sorted(out))


def _pool(pool: PoolCheck) -> str:
    if pool.status != "ok" or pool.remaining_percent is None:
        return f"{pool.window} unreadable"
    text = f"{pool.window} {int(round(pool.remaining_percent))}% left"
    if pool.headroom_percent is not None:
        text += f", headroom {int(round(pool.headroom_percent))}%"
    if pool.resets_at:
        text += f", resets {format_reset_utc(pool.resets_at)}"
    return text


def _candidate(candidate: LevelCandidate, names: Mapping[str, str]) -> str:
    via = " (fallback)" if candidate.fallback else ""
    where = (
        f" on {display_name(names, candidate.machine_id)}"
        if candidate.machine_id
        else ""
    )
    selection = (
        f"{candidate.surface} {candidate.model} {candidate.reasoning_effort}"
        f"{via}{where}"
    )
    if candidate.blocked:
        return f"    ✗ {selection} · {candidate.blocked}"
    pools = " · ".join(_pool(pool) for pool in candidate.pools)
    mark = "→" if candidate.chosen else "✓"
    return f"    {mark} {selection} · {pools or 'no published meter'}"


def level_readout_lines(
    readout: LevelReadout | None, *, machine_names: Mapping[str, str]
) -> list[str]:
    """The level block: live workers per surface, then each level's options."""
    if readout is None:
        return []
    workers = " · ".join(f"{surface} {n}" for surface, n in readout.live_workers)
    lines = [
        f"{LEVELS_HEADING} ({readout.source}) — launch with --level; "
        f"live workers: {workers or 'none'}"
    ]
    if readout.unavailable:
        return [*lines, f"  unavailable: {readout.unavailable}"]
    for glyph, placement in readout.levels:
        head = f"  {placement.level} {glyph}"
        if placement.chosen is None:
            head += " no capacity: a launch at this level refuses"
        else:
            head += f" next → {placement.reason}"
        lines.append(head)
        lines.extend(_candidate(c, machine_names) for c in placement.candidates)
    return lines


def level_override_lines(overrides: Iterable[tuple[str, str]]) -> list[str]:
    rows = [f"  {ref}  {text}" for ref, text in overrides]
    return [OVERRIDES_HEADING, *rows] if rows else []


__all__ = [
    "LEVELS_HEADING",
    "LevelReadout",
    "OVERRIDES_HEADING",
    "level_override_lines",
    "level_readout_lines",
    "read_level_overrides",
    "read_level_readout",
]

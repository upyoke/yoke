"""Choose which option of a level a launch runs, and on which machine.

A launch that names a level, not a surface, is placed here. Every option of
the level is weighed on every machine the caller may use that offers its
surface and has lane capacity, against only the quota pools that option's
model draws on (:mod:`session_launch_level_pools`). A Cursor option's
fallback is weighed on a machine only where the option's own pool is
confirmed empty there.

The choice, in order:

1. **Spread.** A candidate on a surface with no live worker and more than
   100% headroom wins first, so idle quota that cannot run out before its
   reset is put to work rather than left behind.
2. **Most headroom.** Otherwise the candidate with the most binding headroom
   wins; a candidate whose pools publish no readable meter ranks below every
   readable one.
3. **Order.** The level's option order, then machine id, break ties.

When no option can launch anywhere, the launch is refused with every option
and the pool or eligibility rule that blocked it. The Levels page previews its
next launch through here, so it never predicts a different answer. A level
never borrows another level's options: steering decides whether to relaunch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Sequence

from yoke_contracts.levels import Level, LevelOption
from yoke_core.domain.machine_launch_access import filter_by_machine_access
from yoke_core.domain.refusal_recovery import compose_refusal
from yoke_core.domain.session_launch_level_pools import (
    PoolCheck,
    binding_pool,
    exhausted_pool,
    live_workers,
    option_pools,
)
from yoke_core.domain.session_launch_machine_pin import (
    MACHINE_UNRESOLVED,
    resolve_launch_machine_pin,
)
from yoke_core.domain.session_launch_types import (
    EligibleRelay,
    LaunchAuthorization,
    LaunchEligibilityPort,
    SessionLaunchError,
)
from yoke_core.domain.steering_fleet_report_limits import load_plan_limits
from yoke_core.domain.universe_levels import effective_levels

LEVEL_NO_CAPACITY = "level_no_capacity"
LEVEL_UNKNOWN = "level_unknown"
RULE_SPREAD = "spread"
RULE_HEADROOM = "most_headroom"
#: Above this headroom a surface with no live worker takes the launch.
SPREAD_HEADROOM_PERCENT = 100.0


@dataclass(frozen=True)
class LevelCandidate:
    """One option weighed on one machine, and what decided it."""

    option_index: int
    surface: str
    model: str
    reasoning_effort: str
    context_window_tokens: int | None
    machine_id: str | None
    fallback: bool
    pools: tuple[PoolCheck, ...] = ()
    headroom_percent: float | None = None
    headroom_window: str | None = None
    live_workers: int = 0
    blocked: str | None = None
    chosen: bool = False

    @property
    def label(self) -> str:
        where = f" on {self.machine_id}" if self.machine_id else ""
        via = " (fallback)" if self.fallback else ""
        return f"{self.surface} {self.model} {self.reasoning_effort}{via}{where}"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["pools"] = [pool.to_dict() for pool in self.pools]
        out["label"] = self.label
        return out


@dataclass(frozen=True)
class LevelPlacement:
    """The level a launch asked for, every candidate weighed, and the winner."""

    level: str
    levels_source: str
    candidates: tuple[LevelCandidate, ...]
    chosen: LevelCandidate | None
    rule: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "levels_source": self.levels_source,
            "chosen": self.chosen.to_dict() if self.chosen else None,
            "rule": self.rule,
            "reason": self.reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _level(levels: Sequence[Level], name: str, source: str) -> Level:
    wanted = str(name or "").strip().upper()
    for level in levels:
        if level.name == wanted:
            return level
    raise SessionLaunchError(
        LEVEL_UNKNOWN,
        compose_refusal(
            f"Level {name!r} is not defined",
            evaluated=f"{source} levels: {', '.join(lv.name for lv in levels)}",
            recovery="Name one of those levels with --level",
        ),
    )


def _percent(value: float | None) -> str:
    return "unreadable" if value is None else f"{int(round(value))}%"


def _ineligible_reason(snapshot: Any, surface: str, denials: dict[str, str]) -> str:
    """Why no machine could take this surface, in the snapshot's own words."""
    parts = [*snapshot.rejection_codes, *snapshot.rejection_details]
    parts.extend(f"{machine}: {why}" for machine, why in sorted(denials.items()))
    detail = "; ".join(dict.fromkeys(str(part) for part in parts if part))
    return f"no usable machine offers {surface}" + (f" ({detail})" if detail else "")


def _weigh(
    option: LevelOption,
    *,
    index: int,
    relay: EligibleRelay,
    limits: Sequence[Any],
    workers: dict[str, int],
    now: str,
    fallback: bool,
) -> LevelCandidate:
    pools = option_pools(
        limits,
        machine_id=relay.machine_id,
        surface=option.surface,
        model=option.model,
        now=now,
    )
    empty = exhausted_pool(pools)
    binding = binding_pool(pools)
    return LevelCandidate(
        option_index=index,
        surface=option.surface,
        model=option.model,
        reasoning_effort=option.reasoning_effort,
        context_window_tokens=option.context_window_tokens,
        machine_id=relay.machine_id,
        fallback=fallback,
        pools=pools,
        headroom_percent=binding.headroom_percent if binding else None,
        headroom_window=binding.window if binding else None,
        live_workers=workers.get(option.surface, 0),
        blocked=(
            f"{empty.window} pool exhausted (resets {empty.resets_at or 'unknown'})"
            if empty
            else None
        ),
    )


def _candidates(
    conn: Any,
    level: Level,
    *,
    auth: LaunchAuthorization,
    project_id: int,
    machine_id: str | None,
    now: str,
    eligibility: LaunchEligibilityPort,
) -> list[LevelCandidate]:
    limits = load_plan_limits(conn, project_id=project_id, now=now)
    workers = live_workers(conn)
    weighed: list[LevelCandidate] = []
    for index, option in enumerate(level.options):
        snapshot, denials = filter_by_machine_access(
            conn,
            eligibility(
                conn,
                project_id=project_id,
                surface=option.surface,
                machine_id=machine_id,
                now=now,
            ),
            actor_id=auth.actor_id,
            project_id=project_id,
            is_admin=auth.can_administer_project,
        )
        relays = {relay.machine_id: relay for relay in reversed(snapshot.relays)}
        if not relays:
            weighed.append(
                LevelCandidate(
                    option_index=index,
                    surface=option.surface,
                    model=option.model,
                    reasoning_effort=option.reasoning_effort,
                    context_window_tokens=option.context_window_tokens,
                    machine_id=None,
                    fallback=False,
                    blocked=_ineligible_reason(snapshot, option.surface, denials),
                )
            )
            continue
        for machine in sorted(relays):
            primary = _weigh(
                option,
                index=index,
                relay=relays[machine],
                limits=limits,
                workers=workers,
                now=now,
                fallback=False,
            )
            weighed.append(primary)
            if primary.blocked and option.fallback is not None:
                weighed.append(
                    _weigh(
                        option.fallback,
                        index=index,
                        relay=relays[machine],
                        limits=limits,
                        workers=workers,
                        now=now,
                        fallback=True,
                    )
                )
    return weighed


def _choose(open_: list[LevelCandidate]) -> tuple[LevelCandidate, str]:
    def rank(candidate: LevelCandidate) -> tuple[Any, ...]:
        readable = candidate.headroom_percent is not None
        return (
            not readable,
            -(candidate.headroom_percent or 0.0),
            candidate.option_index,
            candidate.fallback,
            candidate.machine_id or "",
        )

    spread = [
        candidate
        for candidate in open_
        if candidate.live_workers == 0
        and (candidate.headroom_percent or 0.0) > SPREAD_HEADROOM_PERCENT
    ]
    if spread:
        return min(spread, key=rank), RULE_SPREAD
    return min(open_, key=rank), RULE_HEADROOM


def _reason(chosen: LevelCandidate, rule: str, open_: list[LevelCandidate]) -> str:
    headroom = _percent(chosen.headroom_percent)
    window = f" ({chosen.headroom_window})" if chosen.headroom_window else ""
    if len(open_) == 1:
        return f"only option with capacity: {chosen.label}, headroom {headroom}{window}"
    if rule == RULE_SPREAD:
        return (
            f"spread rule: no live worker on {chosen.surface} and headroom "
            f"{headroom}{window} above "
            f"{int(SPREAD_HEADROOM_PERCENT)}%; chose {chosen.label}"
        )
    return f"most headroom: {chosen.label} at {headroom}{window}"


def _refusal(level: Level, weighed: list[LevelCandidate]) -> str:
    blocked = "; ".join(f"{c.label}: {c.blocked}" for c in weighed)
    return compose_refusal(
        f"No {level.name} option has capacity",
        evaluated=blocked or "the level has no options",
        recovery=(
            "Relaunch at another level with --level, wait for a named reset, "
            "or launch an exact selection with --surface"
        ),
    )


def place_level(
    conn: Any,
    *,
    auth: LaunchAuthorization,
    project_id: int,
    level: str,
    machine_id: str | None,
    now: str,
    eligibility: LaunchEligibilityPort,
) -> LevelPlacement:
    """Weigh every option of ``level`` and choose one, or say why none fits."""
    levels, source = effective_levels(conn, project_id)
    wanted = _level(levels, level, source)
    pin = resolve_launch_machine_pin(conn, machine_id)
    if pin.unresolved:
        raise SessionLaunchError(MACHINE_UNRESOLVED, str(pin.refusal_reason))
    weighed = _candidates(
        conn,
        wanted,
        auth=auth,
        project_id=project_id,
        machine_id=pin.machine_id,
        now=now,
        eligibility=eligibility,
    )
    open_ = [candidate for candidate in weighed if candidate.blocked is None]
    if not open_:
        return LevelPlacement(
            wanted.name, source, tuple(weighed), None, None, _refusal(wanted, weighed)
        )
    chosen, rule = _choose(open_)
    reason = _reason(chosen, rule, open_)
    chosen = replace(chosen, chosen=True)
    marked = tuple(
        chosen
        if (c.option_index, c.fallback, c.machine_id)
        == (chosen.option_index, chosen.fallback, chosen.machine_id)
        else c
        for c in weighed
    )
    return LevelPlacement(wanted.name, source, marked, chosen, rule, reason)


__all__ = [
    "LEVEL_NO_CAPACITY",
    "LEVEL_UNKNOWN",
    "LevelCandidate",
    "LevelPlacement",
    "RULE_HEADROOM",
    "RULE_SPREAD",
    "SPREAD_HEADROOM_PERCENT",
    "place_level",
]

"""Choose which option of a level a launch runs, and on which machine.

Each model/minimum-effort row expands into observed native selectors, then
uses the existing machine, quota, spread and headroom rules. Cursor's earlier
monthly pool is preferred among available Cursor candidates.

Empty and blocked candidates are skipped. Cursor pool order filters Cursor
candidates first; spread, headroom and configuration position then select from
all surfaces without adding an order to other vendors. Headroom is per worker:
the binding pool's headroom split among its live workers and this launch.

When no option can launch anywhere, the launch is refused with every option
and the pool or eligibility rule that blocked it. Launch previews use the same
selection. A level never borrows another level's options; capacity recovery
excludes the refused model.
"""

from __future__ import annotations

from datetime import datetime
from dataclasses import replace
from typing import Any, Sequence

from yoke_contracts.levels import Level
from yoke_contracts.session_control.model_selection import SURFACE_EFFORT_LEVELS
from yoke_core.domain.level_native_selections import (
    NativeLevelSelection,
    catalog_supports,
    native_selections,
)
from yoke_core.domain.session_launch_machine_models import machine_native_models
from yoke_core.domain.session_launch_machine_rejections import ineligible_reason
from yoke_core.domain.session_model_catalog import current_model_records
from yoke_contracts.timestamps import as_utc
from yoke_core.domain.machine_launch_access import filter_by_machine_access
from yoke_core.domain.machine_registry import display_name, machine_names
from yoke_core.domain.refusal_recovery import compose_refusal
from yoke_core.domain.quota_pool_order import pool_preference, read_pool_order
from yoke_core.domain.session_launch_level_candidate import (
    LevelCandidate,
    LevelPlacement,
)
from yoke_core.domain.session_launch_level_pools import (
    WorkerCounts,
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
RULE_HEADROOM = "most_headroom"
RULE_SPREAD = "spread"
SPREAD_HEADROOM_PERCENT = 100.0


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


def _weigh(
    option: NativeLevelSelection,
    *,
    index: int,
    relay: EligibleRelay,
    names: dict[str, str],
    limits: Sequence[Any],
    workers: WorkerCounts,
    now: datetime,
) -> LevelCandidate:
    pools = option_pools(
        limits,
        machine_id=relay.machine_id,
        surface=option.surface,
        model=option.model,
        now=now,
        workers=workers,
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
        machine_name=display_name(names, relay.machine_id),
        pools=pools,
        headroom_percent=binding.share_percent if binding else None,
        headroom_window=binding.window if binding else None,
        live_workers=binding.workers if binding else 0,
        blocked=(
            f"{empty.window} pool exhausted and {empty.extra_label} "
            f"(resets {empty.to_dict()['resets_at'] or 'unknown'})"
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
    now: datetime,
    eligibility: LaunchEligibilityPort,
) -> list[LevelCandidate]:
    limits = load_plan_limits(conn, project_id=project_id, now=now)
    workers = live_workers(conn)
    names = machine_names(conn)
    weighed: list[LevelCandidate] = []
    records = current_model_records(conn)
    native = {}
    for surface in SURFACE_EFFORT_LEVELS:
        snapshot, denials = filter_by_machine_access(
            conn,
            eligibility(
                conn,
                project_id=project_id,
                surface=surface,
                machine_id=machine_id,
                now=now,
            ),
            actor_id=auth.actor_id,
            project_id=project_id,
            is_admin=auth.can_administer_project,
        )
        relays = {relay.machine_id: relay for relay in reversed(snapshot.relays)}
        for index, entry in enumerate(level.options):
            if not catalog_supports(surface, entry.model, records):
                continue
            if not relays:
                weighed.append(
                    LevelCandidate(
                        option_index=index,
                        surface=surface,
                        model=entry.model,
                        reasoning_effort=entry.min_effort,
                        context_window_tokens=None,
                        machine_id=None,
                        blocked=ineligible_reason(snapshot, surface, denials),
                    )
                )
            for machine in sorted(relays):
                if machine not in native:
                    native[machine] = machine_native_models(conn, machine_id=machine)
                selections, unavailable = native_selections(
                    entry,
                    surface=surface,
                    reading=native[machine].get(surface),
                    records=records,
                )
                if unavailable:
                    weighed.append(
                        LevelCandidate(
                            option_index=index,
                            surface=surface,
                            model=entry.model,
                            reasoning_effort=entry.min_effort,
                            context_window_tokens=None,
                            machine_id=machine,
                            blocked=unavailable,
                        )
                    )
                for selection in selections:
                    weighed.append(
                        _weigh(
                            selection,
                            index=index,
                            relay=relays[machine],
                            names=names,
                            limits=limits,
                            workers=workers,
                            now=now,
                        )
                    )
    return weighed


def _choose(
    open_: list[LevelCandidate], consumption_order=None
) -> tuple[LevelCandidate, str]:
    from yoke_core.domain.quota_pool_order import DEFAULT_CURSOR_QUOTA_ORDER

    order = consumption_order or DEFAULT_CURSOR_QUOTA_ORDER
    cursor = [candidate for candidate in open_ if candidate.surface == "cursor-cli"]
    preferred = min(
        (pool_preference(order, model=candidate.model) for candidate in cursor),
        default=None,
    )
    available = [
        candidate
        for candidate in open_
        if candidate.surface != "cursor-cli"
        or pool_preference(order, model=candidate.model) == preferred
    ]

    def rank(candidate):
        return (
            candidate.headroom_percent is None,
            -(candidate.headroom_percent or 0.0),
            candidate.option_index,
            candidate.machine_id or "",
        )

    spread = [
        candidate
        for candidate in available
        if candidate.live_workers == 0
        and (candidate.headroom_percent or 0.0) > SPREAD_HEADROOM_PERCENT
    ]
    return (
        (min(spread, key=rank), RULE_SPREAD)
        if spread
        else (min(available, key=rank), RULE_HEADROOM)
    )


def _reason(chosen: LevelCandidate, rule: str, open_: list[LevelCandidate]) -> str:
    headroom = _percent(chosen.headroom_percent)
    shared = f", split {chosen.live_workers + 1} ways" if chosen.live_workers else ""
    window = f" ({chosen.headroom_window}{shared})" if chosen.headroom_window else ""
    if len(open_) == 1:
        return f"only option with capacity: {chosen.label}, headroom {headroom}{window}"
    if rule == RULE_SPREAD:
        return f"spread rule: no live worker draws on this pool; {chosen.label}, headroom {headroom}{window} above {int(SPREAD_HEADROOM_PERCENT)}%"
    return f"most headroom per worker: {chosen.label} at {headroom}{window}"


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
    now: datetime,
    eligibility: LaunchEligibilityPort,
    excluded_models: tuple[str, ...] = (),
) -> LevelPlacement:
    """Weigh every option of ``level`` and choose one, or say why none fits."""
    now = as_utc(now)
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
    if excluded_models:
        from yoke_core.domain.session_capacity_recovery import (
            capacity_catalog,
            capacity_model_key,
        )

        records = capacity_catalog(conn, now=now)
        weighed = [
            replace(c, blocked="model_capacity_excluded: provider refused this model")
            if capacity_model_key(c.surface, c.model, records=records)
            in excluded_models
            else c
            for c in weighed
        ]
    open_ = [candidate for candidate in weighed if candidate.blocked is None]
    if not open_:
        return LevelPlacement(
            wanted.name, source, tuple(weighed), None, None, _refusal(wanted, weighed)
        )
    chosen, rule = _choose(open_, read_pool_order(conn))
    reason = _reason(chosen, rule, open_)
    chosen = replace(chosen, chosen=True)
    marked = tuple(
        chosen
        if (c.option_index, c.surface, c.model, c.reasoning_effort, c.machine_id)
        == (
            chosen.option_index,
            chosen.surface,
            chosen.model,
            chosen.reasoning_effort,
            chosen.machine_id,
        )
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

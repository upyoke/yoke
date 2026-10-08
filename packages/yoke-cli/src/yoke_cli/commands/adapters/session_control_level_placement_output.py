"""Render how a level launch chose its option: level, winner, every pool read.

The one line a reader needs is the level, the option that won, and why;
the table under it is the evidence -- each option weighed on each machine,
the quota pools its model draws on, the live workers already there, and the
rule or pool that blocked it.
"""

from __future__ import annotations

from typing import Any, Mapping, TextIO

from yoke_cli.commands.adapters.session_control_human_output import (
    Column,
    write_table,
)


def _percent(value: Any) -> str:
    return "unreadable" if value is None else f"{int(round(float(value)))}%"


def level_rows(placement: Any) -> list[tuple[str, Any]]:
    """Summary rows for a level launch, or nothing for an explicit one."""
    if not isinstance(placement, Mapping):
        return []
    chosen = placement.get("chosen")
    label = chosen.get("label") if isinstance(chosen, Mapping) else None
    return [
        ("Level", f"{placement.get('level')} ({placement.get('levels_source')})"),
        ("Level option", label or "none had capacity"),
        ("Level choice", placement.get("reason")),
    ]


def _pools_cell(row: Mapping[str, Any]) -> str:
    pools = row.get("pools") or []
    if not pools:
        return "no meter covers this model"
    return "; ".join(
        f"{pool.get('window')} {_percent(pool.get('remaining_percent'))} left, "
        f"headroom {_percent(pool.get('headroom_percent'))}"
        for pool in pools
        if isinstance(pool, Mapping)
    )


_COLUMNS: tuple[Column, ...] = (
    ("OPTION", lambda row: row.get("label"), 48),
    ("POOLS CHECKED", _pools_cell, 60),
    ("HEADROOM", lambda row: _percent(row.get("headroom_percent")), 10),
    ("LIVE", lambda row: row.get("live_workers"), 5),
    ("BLOCKED", lambda row: row.get("blocked") or "", 48),
    ("CHOSEN", lambda row: "yes" if row.get("chosen") else "", 7),
)


def write_level_candidates(placement: Any, stdout: TextIO) -> None:
    """The weighed-options table, written only for a level launch."""
    if not isinstance(placement, Mapping):
        return
    write_table(
        "LEVEL OPTIONS WEIGHED",
        _COLUMNS,
        placement.get("candidates") or [],
        stdout,
        empty="The level has no options.",
    )


__all__ = ["level_rows", "write_level_candidates"]

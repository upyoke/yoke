"""Resolve a launch ``--machine`` pin to one registered machine id."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.machine_registry import marker

MACHINE_UNRESOLVED = "machine_unresolved"
_LIST_COMMAND = "yoke machine list"


@dataclass(frozen=True)
class LaunchMachinePin:
    """The machine a launch ``--machine`` pin names, or why it does not."""

    machine_id: str | None
    unresolved_value: str | None = None
    refusal_reason: str | None = None

    @property
    def unresolved(self) -> bool:
        return self.refusal_reason is not None


def _cell(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return row[index]


def _collect(conn: Any, sql: str, params: tuple[Any, ...]) -> set[str]:
    ids: set[str] = set()
    for row in conn.execute(sql, params).fetchall():
        value = str(_cell(row, "machine_id", 0) or "").strip()
        if value:
            ids.add(value)
    return ids


def _matching_machine_ids(conn: Any, value: str) -> set[str]:
    placeholder = marker(conn)
    params = (value, value)
    ids = _collect(
        conn,
        "SELECT machine_id FROM machines "
        f"WHERE machine_id = {placeholder} OR LOWER(name) = LOWER({placeholder})",
        params,
    )
    ids.update(
        _collect(
            conn,
            "SELECT DISTINCT machine_id FROM session_relays "
            f"WHERE machine_id = {placeholder} OR LOWER(hostname) = LOWER({placeholder})",
            params,
        )
    )
    return ids


def _refusal(value: str, *, matched: int) -> str:
    quoted = f"--machine {value}"
    if matched:
        return (
            f"{quoted} matched {matched} machines. Recovery: run `{_LIST_COMMAND}` "
            "and pass one listed machine id."
        )
    return (
        f"{quoted} did not resolve to a machine id. Recovery: run `{_LIST_COMMAND}` "
        "and pass a listed machine id or the machine's registered name."
    )


def resolve_launch_machine_pin(conn: Any, pin: str | None) -> LaunchMachinePin:
    """Map a ``--machine`` pin to one machine id.

    Accepts a machine id, a registered name, or a relay hostname. An empty pin
    leaves the launch unpinned. Zero or several matches are
    ``machine_unresolved`` rather than an absent relay.
    """
    text = str(pin or "").strip()
    if not text:
        return LaunchMachinePin(machine_id=None)
    ids = _matching_machine_ids(conn, text)
    if len(ids) == 1:
        return LaunchMachinePin(machine_id=next(iter(ids)))
    return LaunchMachinePin(
        machine_id=None,
        unresolved_value=text,
        refusal_reason=_refusal(text, matched=len(ids)),
    )


__all__ = [
    "MACHINE_UNRESOLVED",
    "LaunchMachinePin",
    "resolve_launch_machine_pin",
]

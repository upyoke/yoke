"""Resolve a launch ``--machine`` pin to one registered, live machine id."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.machine_registry import marker

MACHINE_UNRESOLVED = "machine_unresolved"
_LIST_COMMAND = "yoke machine list"
_CANDIDATE_LIMIT = 10


@dataclass(frozen=True)
class LaunchMachinePin:
    """The machine a launch ``--machine`` pin names, or why it does not."""

    machine_id: str | None
    unresolved_value: str | None = None
    refusal_reason: str | None = None

    @property
    def unresolved(self) -> bool:
        return self.refusal_reason is not None


@dataclass(frozen=True)
class _Candidate:
    machine_id: str
    name: str
    last_seen_at: str


def _cell(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return row[index]


def _text(row: Any, name: str, index: int) -> str:
    return str(_cell(row, name, index) or "").strip()


def _matching_machines(conn: Any, value: str) -> dict[str, _Candidate]:
    """Live machines whose id, registered name or relay hostname is ``value``.

    A retired machine never matches, whether named directly or through a
    relay it once ran.
    """
    p = marker(conn)
    found: dict[str, _Candidate] = {}
    for row in conn.execute(
        "SELECT machine_id, name, last_seen_at FROM machines "
        f"WHERE retired_at IS NULL AND (machine_id = {p} OR LOWER(name) = LOWER({p}))",
        (value, value),
    ).fetchall():
        machine_id = _text(row, "machine_id", 0)
        if machine_id:
            found[machine_id] = _Candidate(
                machine_id, _text(row, "name", 1), _text(row, "last_seen_at", 2)
            )
    for row in conn.execute(
        "SELECT r.machine_id, COALESCE(m.name, r.hostname) AS name, "
        "COALESCE(m.last_seen_at, r.last_seen_at) AS last_seen_at "
        "FROM session_relays r LEFT JOIN machines m ON m.machine_id = r.machine_id "
        f"WHERE m.retired_at IS NULL AND (r.machine_id = {p} "
        f"OR LOWER(r.hostname) = LOWER({p}))",
        (value, value),
    ).fetchall():
        machine_id = _text(row, "machine_id", 0)
        if machine_id and machine_id not in found:
            found[machine_id] = _Candidate(
                machine_id, _text(row, "name", 1), _text(row, "last_seen_at", 2)
            )
    return found


def _names_test_machine(conn: Any, value: str) -> bool:
    from yoke_core.domain.machine_qa_host_registrar import host_registrations

    lowered = value.lower()
    return any(
        registration.resource_name.lower() == lowered
        for registration in host_registrations(conn)
    )


def _candidate_lines(candidates: dict[str, _Candidate]) -> list[str]:
    ordered = sorted(
        candidates.values(), key=lambda c: c.last_seen_at, reverse=True
    )
    lines = [
        f"  {c.machine_id} (name {c.name or '-'}, last_seen_at {c.last_seen_at or '-'})"
        for c in ordered[:_CANDIDATE_LIMIT]
    ]
    if len(ordered) > _CANDIDATE_LIMIT:
        lines.append(f"  ... {len(ordered) - _CANDIDATE_LIMIT} more")
    return lines


def _refusal(conn: Any, value: str, candidates: dict[str, _Candidate]) -> str:
    quoted = f"--machine {value}"
    if candidates:
        lines = [
            f"{quoted} matched {len(candidates)} live machines; pass one machine id:",
            *_candidate_lines(candidates),
        ]
    else:
        lines = [
            compose_refusal(
                f"{quoted} did not resolve to a live machine id.",
                recovery=f"run `{_LIST_COMMAND}` and pass a listed machine id.",
            )
        ]
    if _names_test_machine(conn, value):
        lines.append(
            f"{value} is a test machine, reached only through its QA lease; it is "
            "not a launch target. To launch on the Yoke a mission installed there, "
            f"pass the machine id that install registered, listed by `{_LIST_COMMAND}` "
            "on the server it connected to."
        )
    return "\n".join(lines)


def resolve_launch_machine_pin(conn: Any, pin: str | None) -> LaunchMachinePin:
    """Map a ``--machine`` pin to one live machine id.

    Accepts a machine id; a registered name or relay hostname resolves only
    when exactly one live machine carries it. An empty pin leaves the launch
    unpinned. Zero or several matches are ``machine_unresolved`` rather than
    an absent relay, and the refusal lists the live candidates.
    """
    text = str(pin or "").strip()
    if not text:
        return LaunchMachinePin(machine_id=None)
    candidates = _matching_machines(conn, text)
    if len(candidates) == 1:
        return LaunchMachinePin(machine_id=next(iter(candidates)))
    return LaunchMachinePin(
        machine_id=None,
        unresolved_value=text,
        refusal_reason=_refusal(conn, text, candidates),
    )


__all__ = [
    "MACHINE_UNRESOLVED",
    "LaunchMachinePin",
    "resolve_launch_machine_pin",
]

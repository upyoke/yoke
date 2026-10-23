"""The Yoke Machine an exploratory mission's connect registered.

A walk that connects its Test Machine's Yoke install to this control plane
registers a new Machine, and the host keeps that Machine's id as the
top-level ``machine_id`` of ``$HOME/.yoke/config.json``. The walker reads it
through the mission's lease (``yoke qa mission connected-machine``) right
after the connect, and the control plane records it on the mission's docket
as ``connected_machine`` once it proves this mission created it: the id
names a live Machine here, registered at or after the docket was recorded.
That id, never the Test Machine's name, is what a session launch's
``--machine`` takes. Walk-end retires exactly that recorded Machine with
the walking actor's authority and leaves every other Machine alone.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.machine_config.schema import MACHINE_ID_KEY
from yoke_contracts.timestamps import parse_instant, temporal_wire

CONNECTED_MACHINE = "connected_machine"
CONNECTED_MACHINE_RETIREMENT = "connected_machine_retirement"
ABSENT = "connected_machine_absent"
UNREGISTERED = "connected_machine_unregistered"
PREDATES = "connected_machine_predates_mission"
CONFLICT = "connected_machine_conflict"
DOCKET_JUDGED = "connected_machine_docket_judged"
CONFIG_UNREADABLE = "connected_machine_config_unreadable"


class ConnectedMachineRefusal(ValueError):
    """A connected Machine that this mission cannot record, by name."""

    def __init__(self, code: str, message: str, recovery: str) -> None:
        super().__init__(f"{code}: {message}. Recovery: {recovery}")
        self.code = code
        self.recovery = recovery


def launch_hint(machine_id: str) -> str:
    return f"yoke session-control launch create ... --machine {machine_id}"


def walker_connected_machine(walk_flags: str, run_id: int) -> tuple[str, str]:
    """The walker's connected-machine command and the prompt clause teaching it."""
    command = f"yoke qa mission connected-machine {walk_flags} --run-id {run_id}"
    return command, (
        f"Right after a connect step on the Test Machine succeeds, run "
        f"`{command}`: it records the Yoke Machine that connect registered "
        "and prints its machine_id; add `--test-machine NAME` when that connect "
        "ran on a declared companion host. A session launch's `--machine` takes that "
        "registered Machine id. A Test Machine is reached only through its "
        "lease and is never a launch target, and a mission that connected no "
        "install has no launch target. Walk-end retires that Machine. "
    )


def host_machine_id(control: Any) -> str | None:
    """The Machine id the host's Yoke config holds, or None without one."""
    path = f"{control.home}/.yoke/config.json"
    text = control.read_text(path)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ConnectedMachineRefusal(
            CONFIG_UNREADABLE,
            f"{path} on the Test Machine is not JSON ({exc})",
            "repair or remove that file on the host through the lease, then rerun",
        ) from exc
    value = payload.get(MACHINE_ID_KEY) if isinstance(payload, dict) else None
    return str(value).strip() or None if value is not None else None


def _docket(conn: Any, run_id: int) -> tuple[dict[str, Any], Any]:
    from yoke_core.domain.db_helpers import query_one

    row = query_one(
        conn, "SELECT raw_result, started_at FROM qa_runs WHERE id=%s", (run_id,)
    )
    if row is None:
        raise ConnectedMachineRefusal(
            "connected_machine_docket_missing",
            f"mission run {run_id} has no docket",
            "rerun with the --run-id that walk-start printed",
        )
    raw = row["raw_result"]
    docket = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    return docket, parse_instant(row["started_at"])


def recorded_connected_machine(conn: Any, run_id: int) -> dict[str, Any] | None:
    recorded = _docket(conn, run_id)[0].get(CONNECTED_MACHINE)
    return dict(recorded) if isinstance(recorded, dict) else None


def record_connected_machine(
    conn: Any, *, run_id: int, machine_id: str | None, now: Any
) -> dict[str, Any]:
    """Prove this mission's connect created the Machine, then record it."""
    from yoke_core.domain.machine_registry import (
        MachineRegistryError,
        canonical_machine_id,
        get_machine,
    )
    from yoke_core.domain.qa_run_verdict_record import update_qa_run

    if not machine_id:
        raise ConnectedMachineRefusal(
            ABSENT,
            "the Test Machine's Yoke config has no machine_id, so its install "
            "never connected and this mission has no launch target",
            "run the walk's connect step through host-command first; a mission "
            "that connects no install launches nothing",
        )
    docket, walk_began = _docket(conn, run_id)
    try:
        record = get_machine(conn, canonical_machine_id(machine_id))
    except MachineRegistryError:
        record = None
    if record is None or record.retired_at is not None:
        raise ConnectedMachineRefusal(
            UNREGISTERED,
            f"Machine {machine_id} is not a live Machine on this control plane; "
            "the install connected to another Yoke or has not connected",
            "connect the install to this control plane; launches from here "
            "cannot target a Machine registered elsewhere",
        )
    if record.registered_at < walk_began:
        raise ConnectedMachineRefusal(
            PREDATES,
            f"Machine {record.machine_id} was registered at "
            f"{temporal_wire(record.registered_at)}, before this mission began, "
            "so this mission did not create it; it is never recorded or retired",
            "connect a fresh install during the walk, or launch on that Machine "
            "only with its owner's consent",
        )
    recorded = docket.get(CONNECTED_MACHINE)
    if isinstance(recorded, dict):
        if recorded.get("machine_id") == record.machine_id:
            return dict(recorded)
        raise ConnectedMachineRefusal(
            CONFLICT,
            f"this mission already recorded Machine {recorded.get('machine_id')}; "
            f"the host now holds {record.machine_id}",
            "launch on the recorded Machine; walk-end retires only that one, so "
            f"its owner retires {record.machine_id} with `yoke machine retire "
            f"{record.machine_id} --confirm`",
        )
    entry = temporal_wire(
        {
            "machine_id": record.machine_id,
            "name": record.name,
            "registered_at": record.registered_at,
            "recorded_at": parse_instant(now),
        }
    )
    docket[CONNECTED_MACHINE] = entry
    written = update_qa_run(
        conn,
        run_id,
        {"raw_result": json.dumps(docket, sort_keys=True, separators=(",", ":"))},
        unjudged_only=True,
    )
    if recorded_connected_machine(conn, written.run_id) != entry:
        conn.rollback()
        raise ConnectedMachineRefusal(
            DOCKET_JUDGED,
            f"mission run {run_id} already carries a verdict, so its docket is "
            "immutable",
            f"its owner retires Machine {record.machine_id} with `yoke machine "
            f"retire {record.machine_id} --confirm`",
        )
    conn.commit()
    return entry


_OUTCOMES = {UNREGISTERED: "unregistered", PREDATES: "skipped_predates_mission"}
_RETIRE_OUTCOMES = {
    "machine_retire_forbidden": "forbidden",
    "machine_unregistered": "unregistered",
}


def retire_connected_machine(
    conn: Any, *, run_id: int, host_machine_id: str | None, actor_id: int, now: Any
) -> dict[str, Any]:
    """Retire exactly the docket's connected Machine; never any other one."""
    from yoke_core.domain.handlers.machine_registry import _is_admin
    from yoke_core.domain.machine_credentials import retire_with_credentials
    from yoke_core.domain.machine_registry import MachineRegistryError, get_machine

    recorded = recorded_connected_machine(conn, run_id)
    if recorded is None and host_machine_id:
        try:
            recorded = record_connected_machine(
                conn, run_id=run_id, machine_id=host_machine_id, now=now
            )
        except ConnectedMachineRefusal as exc:
            return {
                "machine_id": host_machine_id,
                "outcome": _OUTCOMES.get(exc.code, exc.code),
                "recovery": None if exc.code in _OUTCOMES else exc.recovery,
            }
    if recorded is None:
        return {"machine_id": None, "outcome": "none_recorded", "recovery": None}
    machine_id = str(recorded["machine_id"])
    record = get_machine(conn, machine_id)
    if record is not None and record.retired_at is not None:
        return {
            "machine_id": machine_id,
            "outcome": "already_retired",
            "recovery": None,
        }
    try:
        retire_with_credentials(
            conn,
            machine_id=machine_id,
            actor_id=int(actor_id),
            is_admin=_is_admin(conn, int(actor_id)),
            now=now,
        )
    except MachineRegistryError as exc:
        return {
            "machine_id": machine_id,
            "outcome": _RETIRE_OUTCOMES.get(exc.code, exc.code),
            "recovery": f"the Machine's owner runs `yoke machine retire "
            f"{machine_id} --confirm`",
        }
    return {"machine_id": machine_id, "outcome": "retired", "recovery": None}


def connected_machine_notices(disposal: dict[str, Any]) -> list[str]:
    """Walk-end lines for a connected Machine left registered, with recovery."""
    retirement = disposal.get(CONNECTED_MACHINE_RETIREMENT) or {}
    if not retirement.get("recovery"):
        return []
    return [
        f"connected_machine_not_retired: Machine {retirement['machine_id']} "
        f"({retirement['outcome']}) is still registered. Recovery: "
        f"{retirement['recovery']}"
    ]


__all__ = [
    "CONNECTED_MACHINE",
    "CONNECTED_MACHINE_RETIREMENT",
    "ConnectedMachineRefusal",
    "connected_machine_notices",
    "host_machine_id",
    "launch_hint",
    "record_connected_machine",
    "recorded_connected_machine",
    "retire_connected_machine",
]

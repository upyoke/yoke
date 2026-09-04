"""Reads and writes for the machine registry.

Registration is the moment an asserted machine id becomes a proved one: the
host presents the id, a human name, and the public half of a key it holds, and
the control plane records the row that every later relay poll is checked
against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import uuid

from yoke_contracts.machine_config.machine_access import (
    DEFAULT_ACCESS,
    normalize_access,
    validate_access,
)
from yoke_core.domain import db_backend, json_helper


MAX_NAME_LENGTH = 128


class MachineRegistryError(ValueError):
    """A registry read or write was refused with a typed code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MachineRecord:
    """One registered Yoke machine as every reader sees it."""

    machine_id: str
    name: str
    owner_actor_id: int
    registered_at: str
    last_seen_at: str | None = None
    access: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_ACCESS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "name": self.name,
            "owner_actor_id": self.owner_actor_id,
            "registered_at": self.registered_at,
            "last_seen_at": self.last_seen_at,
            "access": normalize_access(self.access),
        }


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[index]


def _record(row: Any) -> MachineRecord:
    raw_access = _cell(row, "access", 3)
    if isinstance(raw_access, Mapping):
        access = dict(raw_access)
    else:
        try:
            parsed = json_helper.loads_text(str(raw_access or "{}"))
        except ValueError:
            parsed = {}
        access = parsed if isinstance(parsed, dict) else {}
    last_seen = _cell(row, "last_seen_at", 5)
    return MachineRecord(
        machine_id=str(_cell(row, "machine_id", 0)),
        name=str(_cell(row, "name", 1)),
        owner_actor_id=int(_cell(row, "owner_actor_id", 2)),
        access=normalize_access(access),
        registered_at=str(_cell(row, "registered_at", 4)),
        last_seen_at=str(last_seen) if last_seen else None,
    )


_SELECT = (
    "SELECT machine_id,name,owner_actor_id,access,"
    "registered_at,last_seen_at FROM machines"
)


def canonical_machine_id(value: Any) -> str:
    """Return the canonical UUID form, refusing anything else by name."""
    try:
        parsed = str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise MachineRegistryError(
            "machine_id_invalid", "machine id must be a canonical UUID"
        ) from exc
    if parsed != str(value):
        raise MachineRegistryError(
            "machine_id_invalid", "machine id must be a canonical UUID"
        )
    return parsed


def validate_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > MAX_NAME_LENGTH:
        raise MachineRegistryError(
            "machine_name_invalid",
            f"machine name must be 1-{MAX_NAME_LENGTH} characters",
        )
    return text


def get_machine(conn: Any, machine_id: str) -> MachineRecord | None:
    p = marker(conn)
    row = conn.execute(f"{_SELECT} WHERE machine_id={p}", (str(machine_id),)).fetchone()
    return _record(row) if row is not None else None


def require_machine(conn: Any, machine_id: str) -> MachineRecord:
    """Return the row, or refuse by name with the registration recovery."""
    record = get_machine(conn, machine_id)
    if record is None:
        raise MachineRegistryError(
            "machine_unregistered",
            f"machine {machine_id} is not registered in this control plane. "
            "Recovery: run `yoke machine register` on that machine.",
        )
    return record


def list_machines(
    conn: Any, *, owner_actor_id: int | None = None
) -> tuple[MachineRecord, ...]:
    p = marker(conn)
    if owner_actor_id is None:
        rows = conn.execute(f"{_SELECT} ORDER BY name, machine_id").fetchall()
    else:
        rows = conn.execute(
            f"{_SELECT} WHERE owner_actor_id={p} ORDER BY name, machine_id",
            (int(owner_actor_id),),
        ).fetchall()
    return tuple(_record(row) for row in rows)


def machine_names(
    conn: Any, machine_ids: Sequence[str] | None = None
) -> dict[str, str]:
    """Return registered names keyed by machine id, for surfaces people read."""
    wanted = {str(value) for value in machine_ids} if machine_ids is not None else None
    return {
        record.machine_id: record.name
        for record in list_machines(conn)
        if wanted is None or record.machine_id in wanted
    }


def display_name(names: Mapping[str, str], machine_id: str) -> str:
    """Name a machine for a reader, falling back to the id when unregistered."""
    return names.get(machine_id) or machine_id


def register_machine(
    conn: Any,
    *,
    machine_id: str,
    name: str,
    actor_id: int,
    access: Any = None,
    is_admin: bool = False,
    now: str,
) -> tuple[MachineRecord, bool]:
    """Record or refresh one machine, returning the row and whether it is new.

    Registration is idempotent, which is what lets the connect flow run it on
    every ``yoke status``. A machine already registered to another actor is
    refused unless an administrator is asking.
    """
    canonical = canonical_machine_id(machine_id)
    chosen_name = validate_name(name)
    existing = get_machine(conn, canonical)
    if existing is not None and int(existing.owner_actor_id) != int(actor_id):
        if not is_admin:
            raise MachineRegistryError(
                "machine_owner_mismatch",
                f"machine {canonical} is registered to another actor. Recovery: "
                "ask its owner or an administrator to re-register it, or clear "
                "this host's copied machine id and register a fresh one.",
            )
    document = normalize_access(
        access
        if access is not None
        else (existing.access if existing else DEFAULT_ACCESS)
    )
    issues = validate_access(document)
    if issues:
        raise MachineRegistryError("machine_access_invalid", "; ".join(issues))
    owner = int(existing.owner_actor_id) if existing is not None else int(actor_id)
    p = marker(conn)
    if existing is None:
        conn.execute(
            "INSERT INTO machines (machine_id,name,owner_actor_id,"
            f"access,registered_at,last_seen_at) VALUES ({','.join(p for _ in range(6))})",
            (
                canonical,
                chosen_name,
                owner,
                json_helper.dumps_compact(document),
                now,
                now,
            ),
        )
    else:
        conn.execute(
            f"UPDATE machines SET name={p},access={p},"
            f"last_seen_at={p} WHERE machine_id={p}",
            (
                chosen_name,
                json_helper.dumps_compact(document),
                now,
                canonical,
            ),
        )
    conn.commit()
    return require_machine(conn, canonical), existing is None


def set_machine_access(
    conn: Any,
    *,
    machine_id: str,
    access: Any,
    actor_id: int,
    is_admin: bool = False,
    now: str,
) -> MachineRecord:
    """Replace the access document; the owner or an administrator may."""
    record = require_machine(conn, machine_id)
    if int(record.owner_actor_id) != int(actor_id) and not is_admin:
        raise MachineRegistryError(
            "machine_access_forbidden",
            f"only machine {record.machine_id}'s owner or an administrator may "
            "change its access settings.",
        )
    document = normalize_access(access)
    issues = validate_access(document)
    if issues:
        raise MachineRegistryError("machine_access_invalid", "; ".join(issues))
    p = marker(conn)
    conn.execute(
        f"UPDATE machines SET access={p} WHERE machine_id={p}",
        (json_helper.dumps_compact(document), record.machine_id),
    )
    conn.commit()
    return require_machine(conn, record.machine_id)


def touch_machine_seen(conn: Any, *, machine_id: str, now: str) -> None:
    """Stamp liveness from the relay poll that just proved this machine."""
    p = marker(conn)
    conn.execute(
        f"UPDATE machines SET last_seen_at={p} WHERE machine_id={p}",
        (now, str(machine_id)),
    )


__all__ = [
    "MAX_NAME_LENGTH",
    "MachineRecord",
    "MachineRegistryError",
    "canonical_machine_id",
    "display_name",
    "get_machine",
    "list_machines",
    "machine_names",
    "marker",
    "register_machine",
    "require_machine",
    "set_machine_access",
    "touch_machine_seen",
    "validate_name",
]

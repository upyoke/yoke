"""Doctor health check: this machine's local identity matches its registry row."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.config import machine_config
from yoke_core.domain.control_plane_transport import relay
from yoke_core.engines.doctor_applicability import NOT_APPLICABLE
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


SLUG = "machine-registry"
TITLE = "This machine is registered and its proof key matches the registry"
_SHOW_FUNCTION_ID = "machine.show"
_REPAIR = "Repair: run `yoke machine register` on this machine."


def _local_machine_id() -> str:
    try:
        return str(machine_config.load_config().get("machine_id") or "").strip()
    except Exception:  # noqa: BLE001 - a malformed config is reported, not raised
        return ""


def _local_public_key() -> str:
    from yoke_contracts.machine_config.machine_identity import (
        MachineIdentityError,
        machine_public_key,
    )

    try:
        return str(machine_public_key() or "")
    except MachineIdentityError:
        return ""


def _registered_row(conn: Any, machine_id: str) -> Mapping[str, Any] | None:
    if conn is None:
        result = relay(_SHOW_FUNCTION_ID, {"machine_id": machine_id})
        row = result.get("machine")
        return row if isinstance(row, Mapping) else None
    from yoke_core.domain.machine_registry import get_machine

    record = get_machine(conn, machine_id)
    return record.to_dict() if record is not None else None


def hc_machine_registry(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """HC-machine-registry: local machine id and proof key match the registry.

    Doctor previously noticed a *missing* machine id and nothing else, so a
    changed or copied id looked healthy right up until the relay started
    answering for somebody else's box.
    """
    del args
    machine_id = _local_machine_id()
    if not machine_id:
        rec.record(
            SLUG,
            TITLE,
            NOT_APPLICABLE,
            "this machine has no canonical machine id yet; `yoke onboard` "
            "assigns one before registration applies",
        )
        return
    public_key = _local_public_key()
    if not public_key:
        rec.record(
            SLUG, TITLE, "FAIL", f"no local machine key for {machine_id}. {_REPAIR}"
        )
        return
    try:
        row = _registered_row(conn, machine_id)
    except Exception as exc:  # noqa: BLE001 - an unreachable plane is reported
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            f"could not read the registry row for {machine_id}: {exc}. {_REPAIR}",
        )
        return
    if row is None:
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            f"machine {machine_id} is not registered in this control plane, so "
            f"its relay is refused. {_REPAIR}",
        )
        return
    registered_key = str(row.get("proof_public_key") or "")
    if registered_key != public_key:
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            f"machine {machine_id} is registered with a different proof key, so "
            "either this host copied the id or the local key was replaced. "
            "Repair: `yoke machine register --rotate-key` on the machine that "
            "owns this id, or clear the copied `machine_id` from "
            "~/.yoke/config.json here.",
        )
        return
    rec.record(
        SLUG,
        TITLE,
        "PASS",
        f"registered as {row.get('name')!r} with a matching proof key.",
    )


__all__ = ["SLUG", "TITLE", "hc_machine_registry"]

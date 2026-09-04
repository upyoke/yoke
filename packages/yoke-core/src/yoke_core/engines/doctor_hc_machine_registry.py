"""Doctor health check: this machine's local id has a registry row."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.config import machine_config
from yoke_core.domain.control_plane_transport import relay
from yoke_core.engines.doctor_applicability import NOT_APPLICABLE
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


SLUG = "machine-registry"
TITLE = "This machine is registered in the control plane"
_SHOW_FUNCTION_ID = "machine.show"
_REPAIR = "Repair: run `yoke machine register` on this machine."


def _local_machine_id() -> str:
    try:
        return str(machine_config.load_config().get("machine_id") or "").strip()
    except Exception:  # noqa: BLE001 - a malformed config is reported, not raised
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
    """HC-machine-registry: this machine's id resolves to a registry row.

    An unregistered machine is refused at launch by name, and doctor is where
    that is cheap to learn: before the refusal, rather than through it.
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
            f"a launch onto it is refused. {_REPAIR}",
        )
        return
    rec.record(SLUG, TITLE, "PASS", f"registered as {row.get('name')!r}.")


__all__ = ["SLUG", "TITLE", "hc_machine_registry"]

"""Best-effort live surface-disable marks for ``yoke status``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

_LIST_TIMEOUT_S = 8.0


def attach_live_marks(
    report: dict[str, Any],
    config_path: Path,
) -> dict[str, Any]:
    """Attach this machine's live marks without failing the status report."""
    from yoke_contracts.machine_config.runtime import machine_id as read_machine_id

    machine = read_machine_id(config_path)
    marks: list[Mapping[str, Any]] = []
    if machine and _control_plane_ready(report):
        marks = _list_marks(machine)
    if machine:
        report["surface_policies"] = {"machine_id": machine, "marks": marks}
    return report


def _control_plane_ready(report: Mapping[str, Any]) -> bool:
    # Status already probed the plane. A second unbounded dispatcher call
    # hangs product-wheel `yoke status` when the onboard stub 501s POSTs.
    server = report.get("server") or {}
    if isinstance(server, Mapping) and server.get("reachable") is True:
        return True
    db = report.get("db") or {}
    return (
        isinstance(db, Mapping)
        and db.get("relevant") is True
        and db.get("ok") is True
    )


def _list_marks(machine: str) -> list[Mapping[str, Any]]:
    try:
        from yoke_cli.transport.dispatcher import call_dispatcher
        from yoke_contracts.api.function_call import TargetRef

        response = call_dispatcher(
            function_id="session_control.surface_policy.list",
            target=TargetRef(kind="global"),
            payload={"machine_id": machine},
            timeout_s=_LIST_TIMEOUT_S,
        )
        payload = getattr(response, "result", None) or {}
        raw = payload.get("marks") if isinstance(payload, Mapping) else None
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, Mapping)]
    except Exception:
        return []
    return []

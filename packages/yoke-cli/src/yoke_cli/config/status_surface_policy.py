"""Best-effort live surface-disable marks for ``yoke status``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def attach_live_marks(
    report: dict[str, Any],
    config_path: Path,
) -> dict[str, Any]:
    """Attach this machine's live marks without failing the status report."""
    from yoke_contracts.machine_config.runtime import machine_id as read_machine_id

    machine = read_machine_id(config_path)
    if not machine:
        return report
    marks: list[Mapping[str, Any]] = []
    try:
        from yoke_cli.transport.dispatcher import call_dispatcher
        from yoke_contracts.api.function_call import TargetRef

        response = call_dispatcher(
            function_id="session_control.surface_policy.list",
            target=TargetRef(kind="global"),
            payload={"machine_id": machine},
        )
        payload = getattr(response, "result", None) or {}
        raw = payload.get("marks") if isinstance(payload, Mapping) else None
        if isinstance(raw, list):
            marks = [row for row in raw if isinstance(row, Mapping)]
    except Exception:
        marks = []
    report["surface_policies"] = {"machine_id": machine, "marks": marks}
    return report

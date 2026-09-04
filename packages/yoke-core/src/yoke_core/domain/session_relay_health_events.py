"""Fleet-visible events for newly reported relay quarantines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


EVENT_RELAY_REPORT_QUARANTINED = "RelayReportQuarantined"


def _entries(value: object) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    raw = value.get("quarantined_reports")
    if not isinstance(raw, list):
        return {}
    return {
        str(entry.get("report_id")): entry
        for entry in raw
        if isinstance(entry, Mapping) and entry.get("report_id")
    }


def emit_new_relay_quarantines(
    conn: Any,
    *,
    relay_id: str,
    machine_id: str,
    project_ids: Sequence[int],
    previous_health: object,
    relay_health: object,
) -> None:
    """Emit once when a quarantine first arrives in a relay heartbeat."""
    previous = _entries(previous_health)
    for report_id, entry in _entries(relay_health).items():
        if report_id in previous:
            continue
        from yoke_core.domain.events import emit_event

        emit_event(
            EVENT_RELAY_REPORT_QUARANTINED,
            event_kind="system",
            event_type="relay_health",
            source_type="backend",
            severity="ERROR",
            context={
                "relay_id": relay_id,
                "machine_id": machine_id,
                "project_ids": [int(value) for value in project_ids],
                "report_id": report_id,
                "job_kind": entry.get("job_kind"),
                "error_code": entry.get("error_code"),
                "attempts": entry.get("attempts"),
                "quarantined_at": entry.get("quarantined_at"),
            },
            conn=conn,
            transactional=True,
        )


__all__ = ["EVENT_RELAY_REPORT_QUARANTINED", "emit_new_relay_quarantines"]

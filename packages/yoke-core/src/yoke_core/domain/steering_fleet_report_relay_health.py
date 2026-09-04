"""Sustained report-delivery and quarantine conditions from machine relays."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from yoke_contracts.session_control.relay_health import (
    RELAY_NEWER_THAN_SERVER,
    sanitize_relay_health,
)
from yoke_core.domain.steering_fleet_report_detectors import age_seconds, marker


SUSTAINED_RELAY_REPORT_FAILURE_SECONDS = 60


@dataclass(frozen=True)
class RelayHealthCondition:
    relay_id: str
    machine_id: str
    hostname: str
    state: str
    pending_reports: int
    quarantine_count: int
    error_code: str
    failure_count: int
    first_failed_at: str
    last_failed_at: str
    refusal_reason: str
    local_revision: str
    server_revision: str
    recovery: str


def _document(value: object, fallback: object) -> object:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _serves(value: object, project_id: int) -> bool:
    projects = _document(value, [])
    return isinstance(projects, list) and any(
        str(candidate) == str(project_id) for candidate in projects
    )


def relay_health_conditions(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[RelayHealthCondition, ...]:
    """Return quarantine immediately and retry failures once sustained."""
    p = marker(conn)
    rows = conn.execute(
        "SELECT relay_id,machine_id,hostname,project_checkouts,relay_health "
        "FROM session_relays "
        f"WHERE relay_health IS NOT NULL AND relay_health <> {p} "
        "ORDER BY machine_id,relay_id",
        ("",),
    ).fetchall()
    result = []
    for row in rows:
        if not _serves(row["project_checkouts"], project_id):
            continue
        health = sanitize_relay_health(_document(row["relay_health"], {}))
        failure = health.get("report_failure")
        failure = failure if isinstance(failure, dict) else {}
        quarantines = health.get("quarantined_reports")
        quarantines = quarantines if isinstance(quarantines, list) else []
        latest_quarantine = quarantines[-1] if quarantines else {}
        refusal = health.get("run_refusal")
        refusal = refusal if isinstance(refusal, dict) else {}
        first_failed_at = str(failure.get("first_failed_at") or "")
        sustained = (
            age_seconds(first_failed_at, now) or 0
        ) >= SUSTAINED_RELAY_REPORT_FAILURE_SECONDS
        if health["state"] not in {"quarantined", "refused"} and not sustained:
            continue
        result.append(
            RelayHealthCondition(
                relay_id=str(row["relay_id"]),
                machine_id=str(row["machine_id"]),
                hostname=str(row["hostname"]),
                state=str(health["state"]),
                pending_reports=int(health["pending_reports"]),
                quarantine_count=int(health["quarantine_count"]),
                error_code=str(
                    failure.get("error_code")
                    or latest_quarantine.get("error_code")
                    or ""
                ),
                failure_count=int(
                    failure.get("failure_count")
                    or latest_quarantine.get("attempts")
                    or 0
                ),
                first_failed_at=first_failed_at,
                last_failed_at=str(failure.get("last_failed_at") or ""),
                refusal_reason=str(refusal.get("reason") or ""),
                local_revision=str(refusal.get("local_revision") or ""),
                server_revision=str(refusal.get("server_revision") or ""),
                recovery=str(refusal.get("recovery") or ""),
            )
        )
    return tuple(result)


def relay_health_lines(
    conditions: tuple[RelayHealthCondition, ...],
    *,
    machine_id: str | None = None,
) -> list[str]:
    """Render compact machine-safe conditions and concrete recovery."""
    selected = [
        entry
        for entry in conditions
        if machine_id is None or entry.machine_id == machine_id
    ]
    if not selected:
        return []
    lines = ["relay health — attention required:"]
    for entry in selected:
        if entry.refusal_reason == RELAY_NEWER_THAN_SERVER:
            detail = (
                f"refused ({entry.refusal_reason}): relay revision "
                f"{entry.local_revision} is newer than server revision "
                f"{entry.server_revision}; recovery: {entry.recovery}"
            )
            if entry.quarantine_count:
                detail += f"; {entry.quarantine_count} report(s) quarantined"
        elif entry.state == "quarantined":
            detail = (
                f"{entry.quarantine_count} rejected report(s) quarantined; "
                "payloads preserved on that machine"
            )
        else:
            detail = (
                f"{entry.pending_reports} pending report(s), "
                f"{entry.failure_count} consecutive failures ({entry.error_code})"
            )
        lines.append(
            f"  {entry.hostname} {entry.machine_id}/{entry.relay_id} {detail}; "
            "run `yoke relay status` "
            "on that machine, restore wire/transport compatibility, then reconcile"
        )
    return lines


__all__ = [
    "RelayHealthCondition",
    "SUSTAINED_RELAY_REPORT_FAILURE_SECONDS",
    "relay_health_conditions",
    "relay_health_lines",
]

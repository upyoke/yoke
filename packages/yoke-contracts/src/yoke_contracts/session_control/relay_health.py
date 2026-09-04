"""Bounded, body-free health facts published by a machine relay."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MAX_RELAY_QUARANTINE_FACTS = 20
RELAY_NEWER_THAN_SERVER = "relay_newer_than_server"
RELAY_NEWER_THAN_SERVER_RECOVERY = "deploy"
RELAY_HEALTH_STATES = frozenset({"healthy", "retrying", "quarantined", "refused"})


def _text(value: object, *, limit: int = 128) -> str:
    return str(value or "").strip()[:limit]


def _count(value: object) -> int:
    try:
        return max(0, min(int(value or 0), 1_000_000))
    except (TypeError, ValueError):
        return 0


def _failure(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result = {
        "error_code": _text(value.get("error_code")),
        "failure_count": _count(value.get("failure_count")),
        "first_failed_at": _text(value.get("first_failed_at"), limit=32),
        "last_failed_at": _text(value.get("last_failed_at"), limit=32),
    }
    return result if result["error_code"] else {}


def _quarantines(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    seen: set[str] = set()
    for entry in value[-MAX_RELAY_QUARANTINE_FACTS:]:
        if not isinstance(entry, Mapping):
            continue
        report_id = _text(entry.get("report_id"), limit=64)
        if not report_id or report_id in seen:
            continue
        seen.add(report_id)
        result.append(
            {
                "report_id": report_id,
                "job_kind": _text(entry.get("job_kind"), limit=16),
                "error_code": _text(entry.get("error_code")),
                "attempts": _count(entry.get("attempts")),
                "quarantined_at": _text(entry.get("quarantined_at"), limit=32),
            }
        )
    return result


def _run_refusal(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    if _text(value.get("reason")) != RELAY_NEWER_THAN_SERVER:
        return {}
    local_revision = _text(value.get("local_revision"))
    server_revision = _text(value.get("server_revision"))
    if not local_revision or not server_revision:
        return {}
    result = {
        "reason": RELAY_NEWER_THAN_SERVER,
        "local_revision": local_revision,
        "server_revision": server_revision,
        "ahead_by": _count(value.get("ahead_by")),
        "observed_at": _text(value.get("observed_at"), limit=32),
        "recovery": RELAY_NEWER_THAN_SERVER_RECOVERY,
    }
    pinned_release = _text(value.get("pinned_release"))
    if pinned_release:
        result["pinned_release"] = pinned_release
    return result


def sanitize_relay_health(value: object) -> dict[str, Any]:
    """Return only bounded operational facts safe for fleet-wide visibility."""
    document = value if isinstance(value, Mapping) else {}
    failure = _failure(document.get("report_failure"))
    quarantines = _quarantines(document.get("quarantined_reports"))
    refusal = _run_refusal(document.get("run_refusal"))
    pending = _count(document.get("pending_reports"))
    state = (
        "refused"
        if refusal
        else "quarantined"
        if quarantines
        else "retrying"
        if failure or pending
        else "healthy"
    )
    return {
        "state": state,
        "pending_reports": pending,
        "report_failure": failure,
        "run_refusal": refusal,
        "quarantined_reports": quarantines,
        "quarantine_count": max(
            len(quarantines), _count(document.get("quarantine_count"))
        ),
    }


def relay_refuses_jobs(value: object) -> bool:
    """Whether a heartbeat explicitly refuses native work for build skew."""
    return sanitize_relay_health(value)["state"] == "refused"


__all__ = [
    "MAX_RELAY_QUARANTINE_FACTS",
    "RELAY_HEALTH_STATES",
    "RELAY_NEWER_THAN_SERVER",
    "RELAY_NEWER_THAN_SERVER_RECOVERY",
    "relay_refuses_jobs",
    "sanitize_relay_health",
]

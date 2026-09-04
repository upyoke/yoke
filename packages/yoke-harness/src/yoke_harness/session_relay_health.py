"""Durable local health for relay report delivery and quarantine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from threading import Lock

from yoke_contracts.session_control.relay_health import (
    RELAY_NEWER_THAN_SERVER,
    RELAY_NEWER_THAN_SERVER_RECOVERY,
    sanitize_relay_health,
)
from yoke_harness.session_relay_schedule import relay_state_dir


PENDING_REPORT_DIR_NAME = "pending-reports"
QUARANTINED_REPORT_DIR_NAME = "quarantined-reports"
REPORT_ATTEMPT_DIR_NAME = "report-attempts"
RELAY_HEALTH_FILE_NAME = "relay-health.json"
REPORT_QUARANTINE_ATTEMPTS = 3
_LOCK = Lock()
_LOGGER = logging.getLogger(__name__)


def _root(state_dir: Path | None) -> Path:
    return state_dir or relay_state_dir()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(dict(value), separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _health_path(state_dir: Path | None) -> Path:
    return _root(state_dir) / RELAY_HEALTH_FILE_NAME


def _attempt_path(report_path: Path, state_dir: Path | None) -> Path:
    return _root(state_dir) / REPORT_ATTEMPT_DIR_NAME / f"{report_path.stem}.json"


def record_report_failure(
    state_dir: Path | None,
    *,
    error_code: str,
    now: str | None = None,
) -> None:
    """Record one failed dispatch without retaining its error text or body."""
    observed_at = now or _utc_now()
    with _LOCK:
        path = _health_path(state_dir)
        document = _load(path)
        previous = document.get("report_failure")
        failure = dict(previous) if isinstance(previous, Mapping) else {}
        failure.update(
            {
                "error_code": str(error_code or "relay_report_failed")[:128],
                "failure_count": int(failure.get("failure_count") or 0) + 1,
                "first_failed_at": failure.get("first_failed_at") or observed_at,
                "last_failed_at": observed_at,
            }
        )
        document["report_failure"] = failure
        _write(path, document)


def record_relay_run_refusal(
    state_dir: Path | None,
    *,
    pinned_release: str,
    local_revision: str,
    server_revision: str,
    ahead_by: int,
    now: str | None = None,
) -> None:
    """Persist a bounded source/server mismatch for status and heartbeat."""
    with _LOCK:
        path = _health_path(state_dir)
        document = _load(path)
        document["run_refusal"] = {
            "reason": RELAY_NEWER_THAN_SERVER,
            "pinned_release": pinned_release,
            "local_revision": local_revision,
            "server_revision": server_revision,
            "ahead_by": ahead_by,
            "observed_at": now or _utc_now(),
            "recovery": RELAY_NEWER_THAN_SERVER_RECOVERY,
        }
        _write(path, document)


def clear_relay_run_refusal(state_dir: Path | None) -> None:
    with _LOCK:
        path = _health_path(state_dir)
        document = _load(path)
        if "run_refusal" not in document:
            return
        document.pop("run_refusal", None)
        _write(path, document)


def record_rejected_attempt(
    report_path: Path,
    state_dir: Path | None,
    *,
    error_code: str,
) -> int:
    """Increment the bounded-rejection count for one durable report."""
    record_report_failure(state_dir, error_code=error_code)
    with _LOCK:
        path = _attempt_path(report_path, state_dir)
        document = _load(path)
        attempts = int(document.get("attempts") or 0) + 1
        _write(path, {"attempts": attempts, "error_code": error_code})
        return attempts


def clear_report_attempt(report_path: Path, state_dir: Path | None) -> None:
    _attempt_path(report_path, state_dir).unlink(missing_ok=True)


def clear_report_failure_if_drained(state_dir: Path | None) -> None:
    """Clear the active failure once no report remains queued for retry."""
    pending = _root(state_dir) / PENDING_REPORT_DIR_NAME
    if pending.is_dir() and any(pending.glob("*.json")):
        return
    with _LOCK:
        path = _health_path(state_dir)
        document = _load(path)
        if "report_failure" not in document:
            return
        document.pop("report_failure", None)
        _write(path, document)


def quarantine_report(
    report_path: Path,
    payload: Mapping[str, object] | None,
    state_dir: Path | None,
    *,
    error_code: str,
    attempts: int,
    now: str | None = None,
) -> dict[str, object]:
    """Move one rejected payload aside and retain body-free diagnostic facts."""
    directory = _root(state_dir) / QUARANTINED_REPORT_DIR_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    report_id = report_path.stem[:64]
    destination = directory / f"{report_id}.json"
    try:
        report_path.replace(destination)
    except OSError:
        # A malformed file may disappear between discovery and quarantine;
        # the metadata still records the condition for the operator.
        pass
    if destination.exists():
        destination.chmod(0o600)
    metadata = {
        "report_id": report_id,
        "job_kind": str((payload or {}).get("job_kind") or "unknown")[:16],
        "error_code": str(error_code or "relay_report_rejected")[:128],
        "attempts": max(1, int(attempts)),
        "quarantined_at": now or _utc_now(),
    }
    _write(directory / f"{report_id}.meta.json", metadata)
    _LOGGER.error(
        "relay report %s quarantined: server_reason=%s attempts=%d preserved=%s",
        report_id,
        metadata["error_code"],
        metadata["attempts"],
        destination,
    )
    clear_report_attempt(report_path, state_dir)
    clear_report_failure_if_drained(state_dir)
    return metadata


def observe_relay_health(state_dir: Path | None = None) -> dict[str, object]:
    """Read current local health without creating or mutating relay state."""
    try:
        root = _root(state_dir)
    except Exception:
        # Inventory can be inspected before a machine selects an environment.
        return sanitize_relay_health({})
    document = _load(_health_path(state_dir))
    pending_dir = root / PENDING_REPORT_DIR_NAME
    pending = len(list(pending_dir.glob("*.json"))) if pending_dir.is_dir() else 0
    quarantine_dir = root / QUARANTINED_REPORT_DIR_NAME
    metadata_paths = (
        sorted(quarantine_dir.glob("*.meta.json")) if quarantine_dir.is_dir() else []
    )
    document.update(
        {
            "pending_reports": pending,
            "quarantine_count": len(metadata_paths),
            "quarantined_reports": [_load(path) for path in metadata_paths[-20:]],
        }
    )
    return sanitize_relay_health(document)


def relay_health_recovery(health: Mapping[str, object]) -> str:
    """Operator action for the condition shown by ``yoke relay status``."""
    if health.get("state") == "refused":
        refusal = health.get("run_refusal")
        refusal = refusal if isinstance(refusal, Mapping) else {}
        return (
            f"Relay revision {refusal.get('local_revision') or 'unknown'} is newer "
            f"than server revision {refusal.get('server_revision') or 'unknown'}; "
            f"recovery: {RELAY_NEWER_THAN_SERVER_RECOVERY}."
        )
    if health.get("state") == "quarantined":
        return (
            "Rejected reports are preserved under the relay state directory; "
            "align the relay/server wire contract, then replay or reconcile them."
        )
    if health.get("state") == "retrying":
        return (
            "Report delivery is retrying; restore control-plane transport and "
            "leave the relay running so the durable queue can drain."
        )
    return ""


__all__ = [
    "PENDING_REPORT_DIR_NAME",
    "QUARANTINED_REPORT_DIR_NAME",
    "RELAY_HEALTH_FILE_NAME",
    "REPORT_QUARANTINE_ATTEMPTS",
    "clear_relay_run_refusal",
    "clear_report_attempt",
    "clear_report_failure_if_drained",
    "observe_relay_health",
    "quarantine_report",
    "record_relay_run_refusal",
    "record_rejected_attempt",
    "record_report_failure",
    "relay_health_recovery",
]

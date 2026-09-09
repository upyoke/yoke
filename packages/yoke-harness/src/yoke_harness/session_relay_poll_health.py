"""Machine-local control-plane poll outcome for ``yoke relay status``.

Persisted beside report-delivery health, but omitted from
``sanitize_relay_health`` so heartbeats keep the existing fleet contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from yoke_harness.session_relay_health import (
    _LOCK,
    _health_path,
    _load,
    _utc_now,
    _write,
)

_CREDENTIAL_CODES = frozenset(
    {"machine_credential_required", "machine_credential_mismatch"}
)
_CONNECT_THEN_INSTALL = (
    "Control-plane connection failed ({code}). Reconnect this machine with "
    "`yoke connect`, then `yoke relay install` so the loaded service uses the "
    "new credential. `yoke relay install` alone does not mint credentials."
)
_RESTORE_TRANSPORT = (
    "Control-plane connection failed ({code}). Restore control-plane transport "
    "and leave the relay running; `yoke relay install` alone does not mint "
    "credentials."
)


def _bounded_poll(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    status = str(value.get("status") or "").strip()
    if status not in {"ok", "failed", "pending"}:
        return {}
    result: dict[str, object] = {"status": status}
    try:
        consecutive = max(0, min(int(value.get("consecutive_failures") or 0), 1_000_000))
    except (TypeError, ValueError):
        consecutive = 0
    if consecutive:
        result["consecutive_failures"] = consecutive
    code = str(value.get("error_code") or "").strip()[:128]
    if code:
        result["error_code"] = code
    for key in ("first_failed_at", "last_failed_at", "last_succeeded_at"):
        stamp = str(value.get(key) or "").strip()[:32]
        if stamp:
            result[key] = stamp
    return result


def _replace_poll(
    state_dir: Path | None,
    update: Mapping[str, object],
    *,
    drop: tuple[str, ...] = (),
) -> None:
    with _LOCK:
        path = _health_path(state_dir)
        document = _load(path)
        previous = document.get("poll_outcome")
        poll = dict(previous) if isinstance(previous, Mapping) else {}
        poll.update(dict(update))
        for key in drop:
            poll.pop(key, None)
        document["poll_outcome"] = poll
        _write(path, document)


def record_poll_failure(
    state_dir: Path | None,
    *,
    error_code: str,
    now: str | None = None,
) -> None:
    """Record the current control-plane poll refusal for local status."""
    observed = now or _utc_now()
    with _LOCK:
        path = _health_path(state_dir)
        document = _load(path)
        previous = document.get("poll_outcome")
        poll = dict(previous) if isinstance(previous, Mapping) else {}
        continuing = str(poll.get("status") or "") == "failed"
        try:
            count = int(poll.get("consecutive_failures") or 0) if continuing else 0
        except (TypeError, ValueError):
            count = 0
        poll.update(
            {
                "status": "failed",
                "error_code": str(error_code or "poll_failed")[:128],
                "consecutive_failures": count + 1,
                "first_failed_at": (poll.get("first_failed_at") if continuing else None)
                or observed,
                "last_failed_at": observed,
            }
        )
        document["poll_outcome"] = poll
        _write(path, document)


def record_poll_success(state_dir: Path | None, *, now: str | None = None) -> None:
    """Clear the current poll failure after a successful handshake."""
    _replace_poll(
        state_dir,
        {
            "status": "ok",
            "consecutive_failures": 0,
            "last_succeeded_at": now or _utc_now(),
        },
        drop=("error_code", "first_failed_at"),
    )


def reset_poll_outcome(state_dir: Path | None) -> None:
    """Drop inherited current success so a new daemon does not look connected."""
    _replace_poll(
        state_dir,
        {"status": "pending", "consecutive_failures": 0},
        drop=("error_code", "first_failed_at"),
    )


def attach_poll_outcome(
    health: dict[str, object], document: Mapping[str, object]
) -> dict[str, object]:
    """Copy the local poll outcome onto sanitized report-delivery health."""
    poll = _bounded_poll(document.get("poll_outcome"))
    if poll:
        health["poll_outcome"] = poll
    return health


def poll_connection_recovery(health: Mapping[str, object]) -> str:
    """Operator recovery for a failed or not-yet-proven control-plane poll."""
    poll = health.get("poll_outcome")
    poll = poll if isinstance(poll, Mapping) else {}
    status = str(poll.get("status") or "")
    if status == "failed":
        code = str(poll.get("error_code") or "poll_failed")
        template = (
            _CONNECT_THEN_INSTALL if code in _CREDENTIAL_CODES else _RESTORE_TRANSPORT
        )
        return template.format(code=code)
    if status == "pending":
        return (
            "Relay is loaded but has not completed a control-plane poll yet. "
            "Wait for the next cycle; a previous success is not the current verdict."
        )
    return ""


__all__ = [
    "attach_poll_outcome",
    "poll_connection_recovery",
    "record_poll_failure",
    "record_poll_success",
    "reset_poll_outcome",
]

"""Terminate the natives whose supervision record proves they lack authority.

Creating a native and registering it are two separate events, and the gap
between them is where an unattended agent does damage. Natives that never
registered have read the backlog, adopted briefs assigned to other sessions,
and written into the shared checkout with no claim and no lane. A record that
outlives the registration deadline names such a process, and this reaps it.

Delivery removes the record, so a native that registered and read its mandate
is never in scope here: it has authority, and watching it for death is the
relay liveness poll's job through the launch handle.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import time

from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_control.resume import (
    RESUME_INACTIVITY_SECONDS,
    RESUME_RUNAWAY_SECONDS,
)
from yoke_harness.session_launch_containment import (
    MAX_RECORD_BYTES,
    supervised_records,
    supervision_record_path,
)


# A native is contained only after the launch could no longer register, plus
# a margin so the sweep never races the deadline it is backing up.
CONTAINMENT_GRACE_SECONDS = 120
CONTAINMENT_TTL_SECONDS = (
    int(FLEET_KEY_SPECS["fleet.launch_deadline_minutes"].default) * 60
    + CONTAINMENT_GRACE_SECONDS
)
_TERMINATE_WAIT_SECONDS = 2.0


@dataclass(frozen=True)
class ContainmentOutcome:
    """What the sweep did with one supervised native."""

    launch_id: str
    pid: int
    result: str
    native_session_id: str | None = None
    supervision_kind: str = "launch"
    reason: str = "registration_timeout"


def _terminate(pid: int) -> str:
    """Signal the native's whole process group, escalating only if it stays."""
    try:
        group = os.getpgid(pid)
    except OSError:
        return "already_exited"
    try:
        os.killpg(group, signal.SIGTERM)
    except OSError:
        return "already_exited"
    deadline = time.monotonic() + _TERMINATE_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(group, 0)
        except OSError:
            return "terminated"
        time.sleep(0.1)
    try:
        os.killpg(group, signal.SIGKILL)
    except OSError:
        return "terminated"
    return "killed"


def contain_stranded_launch_natives(
    *,
    state_dir: Path | None = None,
    now: float | None = None,
    ttl_seconds: int = CONTAINMENT_TTL_SECONDS,
) -> list[ContainmentOutcome]:
    """Contain launches past registration and resumes past custody limits."""
    current = time.time() if now is None else now
    outcomes: list[ContainmentOutcome] = []
    for path, payload in supervised_records(state_dir):
        recorded_at = payload.get("recorded_at")
        if not isinstance(recorded_at, int):
            continue
        kind = str(payload.get("supervision_kind") or "launch")
        if kind not in {"launch", "resume"}:
            kind = "launch"
        reason = "registration_timeout"
        if kind == "resume":
            activity_at = payload.get("last_activity_at")
            last_activity = float(activity_at) if isinstance(activity_at, int) else 0.0
            capture_path = payload.get("capture_path")
            if isinstance(capture_path, str) and capture_path:
                try:
                    last_activity = max(
                        last_activity, Path(capture_path).stat().st_mtime
                    )
                except OSError:
                    pass
            runaway = current - recorded_at >= RESUME_RUNAWAY_SECONDS
            inactive = current - last_activity >= RESUME_INACTIVITY_SECONDS
            if not runaway and not inactive:
                continue
            reason = "runaway" if runaway else "inactivity"
        elif current - recorded_at < ttl_seconds:
            continue
        outcome = _contain_payload(path, payload, kind=kind, reason=reason)
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes


def contain_launch_native(
    launch_id: str,
    *,
    state_dir: Path | None = None,
    reason: str = "create_failed",
) -> ContainmentOutcome | None:
    """Reap one supervised launch now — the create already failed to register."""
    if not launch_id:
        return None
    path = supervision_record_path(launch_id, state_dir)
    try:
        if not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    kind = str(payload.get("supervision_kind") or "launch")
    if kind != "launch":
        return None
    return _contain_payload(path, payload, kind=kind, reason=reason)


def _contain_payload(
    path: Path,
    payload: dict[str, object],
    *,
    kind: str,
    reason: str,
) -> ContainmentOutcome | None:
    launch_id = str(payload.get("launch_id") or path.stem)
    pid = payload.get("pid")
    native_session_id = payload.get("native_session_id")
    if not isinstance(pid, int) or pid <= 0:
        _drop(path)
        return None
    # A reused pid names a different process entirely; the native this
    # record was written for is already gone.
    if process_start_time(pid) != payload.get("process_start_time"):
        result = "already_exited"
    else:
        result = _terminate(pid)
    _drop(path)
    return ContainmentOutcome(
        launch_id=launch_id,
        pid=pid,
        result=result,
        native_session_id=str(native_session_id) if native_session_id else None,
        supervision_kind=kind,
        reason=reason,
    )


def _drop(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


__all__ = [
    "CONTAINMENT_GRACE_SECONDS",
    "CONTAINMENT_TTL_SECONDS",
    "ContainmentOutcome",
    "contain_launch_native",
    "contain_stranded_launch_natives",
]

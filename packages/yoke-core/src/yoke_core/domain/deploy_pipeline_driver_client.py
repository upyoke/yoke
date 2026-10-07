"""The local deploy driver's attachment to its run: attach, refresh, release.

Every attach names this machine. A refusal names the driver already recorded,
so when that driver ran here and its pid is gone, this process supersedes it at
once instead of waiting ten minutes for its heartbeat to expire: only this
machine can see that the process exited. A driver on another machine is still
judged by its heartbeat alone.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef
from yoke_contracts.machine_config import runtime as machine_config
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.control_plane_function_degradation import REGISTRY_SKEW_CODES
from yoke_core.domain.deploy_pipeline_control_plane import (
    DeploymentControlPlaneError,
)
from yoke_core.domain.deployment_run_driver_attachment import (
    ATTACH_FUNCTION_ID,
    DRIVER_ALREADY_ATTACHED_CODE,
    RELEASE_FUNCTION_ID,
    ROW_LOCK_BUSY_CODE,
)
from yoke_core.domain.session_liveness_pump import (
    HEARTBEAT_INTERVAL_SECONDS,
    SessionLivenessPump,
)


def _local_machine_id() -> str:
    try:
        return machine_config.machine_id() or ""
    except Exception:
        return ""


def _process_gone(pid: int) -> bool:
    """True only when this machine's process table has no *pid* at all."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def exited_local_driver_pid(response: FunctionCallResponse, machine_id: str) -> int:
    """The refusing driver's pid when it ran on *machine_id* and has exited."""
    driver = (response.result or {}).get("driver")
    if not machine_id or not isinstance(driver, dict):
        return 0
    try:
        pid = int(driver.get("pid") or 0)
    except (TypeError, ValueError):
        return 0
    if driver.get("machine_id") != machine_id or pid <= 0 or pid == os.getpid():
        return 0
    return pid if _process_gone(pid) else 0


def _attach(
    run_id: str, payload: Dict[str, Any], exited_driver_pid: int = 0
) -> FunctionCallResponse:
    return call_dispatcher(
        function_id=ATTACH_FUNCTION_ID,
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={**payload, "exited_driver_pid": exited_driver_pid},
    )


def attach_driver(
    run_id: str, *, phase: str, progress_capture: str = ""
) -> Dict[str, Any]:
    """Record this process as the run's driver, or refuse a live other one.

    A registry-skew answer means this client is ahead of the plane; the
    caller proceeds without recording, matching an unconverged column.

    A busy run row is also not a failure to retry: the plane refused rather
    than queueing, so this attempt prints the named holder and returns nothing
    recorded. Saying it out loud is the point -- the driver's own liveness
    stream is the only progress signal a deploy watcher has, and the silence
    while one waited on an abandoned transaction is what made an eleven-minute
    stall unreadable.
    """
    machine_id = _local_machine_id()
    payload = {
        "phase": phase,
        "pid": os.getpid(),
        "progress_capture": progress_capture,
        "machine_id": machine_id,
    }
    response = _attach(run_id, payload)
    code = response.error.code if response.error else ""
    if code == DRIVER_ALREADY_ATTACHED_CODE:
        exited = exited_local_driver_pid(response, machine_id)
        if exited:
            print(
                f"deploy driver pid {exited} on this machine has exited; "
                f"superseding its attachment to {run_id}",
                file=sys.stderr,
            )
            response = _attach(run_id, payload, exited)
            code = response.error.code if response.error else ""
    if response.success:
        return dict(response.result or {})
    if code in REGISTRY_SKEW_CODES:
        return {}
    message = response.error.message if response.error else "request failed"
    if code == ROW_LOCK_BUSY_CODE:
        print(message, file=sys.stderr)
        return {}
    raise DeploymentControlPlaneError(
        f"{ATTACH_FUNCTION_ID} failed: {message}", code=code
    )


def release_driver(run_id: str) -> None:
    """Drop this process's driver attachment; a miss is not a pipeline failure.

    A refusal prints its named reason, including a busy run row's holder and
    recovery, and returns: shutdown must finish so the watcher still writes its
    exit sentinel, and an attachment left behind is superseded by the next
    driver on this machine or expires with its heartbeat.
    """
    response = call_dispatcher(
        function_id=RELEASE_FUNCTION_ID,
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={"pid": os.getpid()},
    )
    if not response.success:
        message = response.error.message if response.error else "request failed"
        print(f"warning: could not release deploy driver: {message}", file=sys.stderr)


class DriverLivenessPump(SessionLivenessPump):
    """Refresh the run's driver attachment for as long as this process is."""

    def __init__(
        self,
        run_id: str,
        *,
        phase: str,
        progress_capture: str = "",
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(interval_seconds=interval_seconds)
        self._run_id = run_id
        self._phase = phase
        self._progress_capture = progress_capture

    def tick(self) -> bool:
        now = self._clock()
        due = now - self._last_refresh >= self._interval
        refreshed = super().tick()
        if due:
            try:
                attach_driver(
                    self._run_id,
                    phase=self._phase,
                    progress_capture=self._progress_capture,
                )
            except DeploymentControlPlaneError as exc:
                print(f"warning: deploy driver heartbeat: {exc}", file=sys.stderr)
        return refreshed


__all__ = [
    "DriverLivenessPump",
    "attach_driver",
    "exited_local_driver_pid",
    "release_driver",
]

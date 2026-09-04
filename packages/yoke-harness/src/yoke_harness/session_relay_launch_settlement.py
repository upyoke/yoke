"""Report the launched natives that died before their session ever registered.

Two things are true at once for a launch whose native is gone: the machine
that started it knows within seconds, and the control plane knows nothing for
ten minutes. That gap is not a waiting period anyone chose — it is the
registration deadline doing its job for the case it was written for, a native
that is still coming up, applied to one that is already over. Four launches on
one afternoon each sat in ``registration_pending`` for the full ten minutes and
then closed with no captured output, while the answer had been on disk the
whole time.

The custody record is what makes this readable without a second registry:
the relay writes one for every native it starts and delivery removes it, so a
record that still exists names a launch whose instruction never reached a
registered session. A record whose recorded pid is no longer the recorded
process therefore names exactly the shape this reports — on every harness,
because every harness writes the same record.

Reporting is all this does. Whether the launch may be closed is the control
plane's judgment, made against the launch row rather than against the file:
a native that registered a session and died a moment later belongs to the
verified-death path, which has a session to ask about.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.process_ancestry import process_start_time
from yoke_contracts.session_control.function_ids import RELAY_LIVENESS_FUNCTION_ID
from yoke_harness.session_launch_containment import (
    release_supervised_native,
    supervised_records,
)
from yoke_harness.session_relay_process_liveness import native_account
from yoke_harness.session_relay_report_delivery import RELAY_REPORT_TIMEOUT_SECONDS


_LOGGER = logging.getLogger(__name__)

Dispatcher = Callable[..., Any]
StartTimeOf = Callable[[int], str | None]


@dataclass(frozen=True)
class UnregisteredLaunchDeath:
    """One launch this machine started whose native is gone unregistered."""

    launch_id: str
    evidence: dict[str, Any]


def unregistered_launch_deaths(
    *,
    state_dir: Path | None = None,
    start_time_of: StartTimeOf = process_start_time,
) -> tuple[UnregisteredLaunchDeath, ...]:
    """Return every still-supervised launch whose native process is gone."""
    deaths: list[UnregisteredLaunchDeath] = []
    for _path, payload in supervised_records(state_dir):
        if str(payload.get("supervision_kind") or "launch") != "launch":
            continue
        launch_id = str(payload.get("launch_id") or "").strip()
        pid = payload.get("pid")
        if not launch_id or not isinstance(pid, int) or pid <= 0:
            continue
        # A reused pid names a different process, so the native this record
        # was written for is gone either way.
        if start_time_of(pid) == payload.get("process_start_time"):
            continue
        deaths.append(
            UnregisteredLaunchDeath(
                launch_id,
                {
                    "native_pid": pid,
                    **native_account(launch_id, state_dir=state_dir),
                },
            )
        )
    return tuple(deaths)


def report_unregistered_launch_deaths(
    dispatcher: Dispatcher,
    inventory: Any,
    *,
    state_dir: Path | None = None,
    timeout_s: int = RELAY_REPORT_TIMEOUT_SECONDS,
    start_time_of: StartTimeOf = process_start_time,
) -> tuple[str, ...]:
    """Report this poll's unregistered native deaths and return those sent.

    The custody record is dropped once the report lands, whatever the control
    plane decided about each launch: the process it named is gone, so nothing
    is left for the containment sweep to terminate and re-reporting it every
    poll would say the same thing forever. A refused report keeps every
    record, so the next poll tries again.
    """
    deaths = unregistered_launch_deaths(
        state_dir=state_dir,
        start_time_of=start_time_of,
    )
    if not deaths:
        return ()
    response = dispatcher(
        function_id=RELAY_LIVENESS_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={
            "relay_id": inventory.relay_id,
            "machine_id": inventory.machine_id,
            "projects": list(inventory.project_ids),
            "launches": [
                {"launch_id": death.launch_id, "evidence": death.evidence}
                for death in deaths
            ],
        },
        timeout_s=timeout_s,
    )
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        _LOGGER.warning(
            "relay launch-death report refused (%s): %s",
            getattr(error, "code", "relay_liveness_failed"),
            getattr(error, "message", ""),
        )
        # The records stay, so the next poll reports these deaths again.
        return ()
    for death in deaths:
        release_supervised_native(death.launch_id, state_dir=state_dir)
    return tuple(death.launch_id for death in deaths)


__all__ = [
    "UnregisteredLaunchDeath",
    "report_unregistered_launch_deaths",
    "unregistered_launch_deaths",
]

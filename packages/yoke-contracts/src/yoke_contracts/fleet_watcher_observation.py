"""Observe a session's standing fleet watcher on the machine that runs it.

Only the machine running the harness can list its processes. Over HTTPS the
hook chain evaluates on the server, which sees none of them, so the client
makes this one observation and ships it in the hook request's
``payload_extra`` under :data:`FLEET_WATCHER_OBSERVATION_KEY`. A local
universe evaluates in-process and collects the same observation the same
way. The evaluating side never infers absence on its own: no observation
means absence is unproven.

Liveness follows the harness manifest's ``agent_wake`` facts
(:mod:`yoke_contracts.harness_wake_capability`), never a harness name:

- idle wake by ``Monitor``: the wrapper and probe are not enough, because a
  Monitor subscription can expire while its wrapper keeps running. A live
  ``yoke watch tail`` subscriber on this session's fleet progress capture is
  required as well.
- idle wake by any other mechanism (``notify_on_output``): the subscription
  lives inside the harness and never appears in a process listing. The
  wrapper and probe are the strongest evidence this machine has; that is a
  designed limit, not a gap to fill with a guess.
- no idle wake: the watcher is the in-turn wrapper, held by an active turn.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.harness_wake_capability import wake_capability_for_harness
from yoke_contracts.session_control.capabilities import capabilities_for_harness


#: Payload key carrying the client's observation to the evaluating side.
FLEET_WATCHER_OBSERVATION_KEY = "yoke_fleet_watcher_observation"

# Keep equal to yoke_core.tools.watch_fleet.{PROBE_MODULE, WRAPPER_MODULE, KIND}
# and yoke_core.tools.watch_tail.WRAPPER_MODULE.
PROBE_MODULE = "yoke_core.domain.fleet_delta_probe"
WRAPPER_MODULE = "yoke_core.tools.watch_fleet"
TAIL_MODULE = "yoke_core.tools.watch_tail"
CAPTURE_PREFIX = "yoke-fleet."
PROGRESS_CAPTURE_PREFIX = "yoke-fleet.progress."

_MONITOR = "Monitor"


def list_process_cmdlines() -> tuple[str, ...]:
    """Return this machine's process command lines, or empty on failure."""
    try:
        completed = subprocess.run(
            ["ps", "-ax", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()
    return tuple(completed.stdout.splitlines())


def _is_tail(line: str) -> bool:
    return "watch tail" in line or TAIL_MODULE in line


def _session_lines(session_id: str, cmdlines: Sequence[str]) -> list[str]:
    marker = f"/sessions/{session_id}/"
    return [line for line in cmdlines if marker in line]


def wrapper_live(session_id: str, cmdlines: Sequence[str]) -> bool:
    """True when a probe runs and this session's fleet wrapper is listed."""
    if not session_id:
        return False
    has_probe = any(PROBE_MODULE in line for line in cmdlines)
    has_wrapper = any(
        not _is_tail(line)
        and (PROBE_MODULE in line or WRAPPER_MODULE in line or CAPTURE_PREFIX in line)
        for line in _session_lines(session_id, cmdlines)
    )
    return has_probe and has_wrapper


def tail_subscriber_live(session_id: str, cmdlines: Sequence[str]) -> bool:
    """True when a ``yoke watch tail`` reads this session's fleet progress."""
    if not session_id:
        return False
    return any(
        _is_tail(line) and PROGRESS_CAPTURE_PREFIX in line
        for line in _session_lines(session_id, cmdlines)
    )


def fleet_watcher_live(
    session_id: str,
    harness_id: str,
    cmdlines: Sequence[str],
) -> bool:
    """Apply the harness's wake model to one process listing."""
    if not wrapper_live(session_id, cmdlines):
        return False
    wake = wake_capability_for_harness(harness_id)
    if wake.idle_wake == "supported" and wake.idle_wake_mechanism == _MONITOR:
        return tail_subscriber_live(session_id, cmdlines)
    return True


def _report_can_inject(harness_id: str, event_name: str) -> bool:
    return any(
        event_name in facts.get("inject_events", ())
        for facts in capabilities_for_harness(harness_id).values()
    )


def observe_fleet_watcher(
    payload: Mapping[str, Any],
    *,
    executor: str,
    event_name: str,
    cmdlines: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return the ``payload_extra`` entry for this hook, or nothing.

    Only events where a fleet report can reach the model pay for a process
    listing. A failed listing returns nothing: absence is not proven.
    """
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return {}
    harness_id = canonical_harness_id(executor)
    if not _report_can_inject(harness_id, event_name):
        return {}
    listed = list_process_cmdlines() if cmdlines is None else tuple(cmdlines)
    if not listed:
        return {}
    return {
        FLEET_WATCHER_OBSERVATION_KEY: {
            "session_id": session_id,
            "live": fleet_watcher_live(session_id, harness_id, listed),
        }
    }


def observed_absent(payload: Mapping[str, Any], session_id: str) -> bool:
    """True only when the client proved this session's watcher absent."""
    observation = payload.get(FLEET_WATCHER_OBSERVATION_KEY)
    return (
        bool(session_id)
        and isinstance(observation, Mapping)
        and observation.get("session_id") == session_id
        and observation.get("live") is False
    )


__all__ = [
    "CAPTURE_PREFIX",
    "FLEET_WATCHER_OBSERVATION_KEY",
    "PROBE_MODULE",
    "PROGRESS_CAPTURE_PREFIX",
    "TAIL_MODULE",
    "WRAPPER_MODULE",
    "fleet_watcher_live",
    "list_process_cmdlines",
    "observe_fleet_watcher",
    "observed_absent",
    "tail_subscriber_live",
    "wrapper_live",
]

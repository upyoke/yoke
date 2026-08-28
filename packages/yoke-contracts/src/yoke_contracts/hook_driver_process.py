"""The process that drove one hook invocation, across the relay boundary.

Every hook invocation is driven by a process: the harness's hook child on
the operator's machine. Over an https control plane that process is not the
one that evaluates the chain — the client relays to the server, and the
server's ``os.getpid()`` names a shared API worker rather than the caller.
Recording the local pid on the evaluating side therefore answers "which
process drove this" with the wrong process on every relayed machine, which
is every hosted one.

So the driving process names itself where it actually runs, and the block
rides the wire in the relay's ``payload_extra`` under
:data:`DRIVER_PAYLOAD_KEY`. The evaluating side reads the block back with
:func:`resolve_driver_process`, which prefers the client's self-report and
falls back to its own pids only when none arrived — the local-universe case,
where the evaluating process IS the driver.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional


#: Payload key carrying the driving process block across the relay.
DRIVER_PAYLOAD_KEY = "yoke_hook_driver"

#: ``origin`` value when the block came from the relay client's self-report.
ORIGIN_CLIENT = "client"

#: ``origin`` value when the evaluating process reported its own pids.
ORIGIN_LOCAL = "local"


def collect_driver_process() -> dict[str, Any]:
    """Report the calling process as the driver of this hook invocation."""
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "origin": ORIGIN_CLIENT,
    }


def _positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def resolve_driver_process(
    payload: Optional[Mapping[str, Any]],
    *,
    hook_event: str = "",
) -> dict[str, Any]:
    """Return the driving process block for *payload*, with *hook_event*.

    A client-supplied block wins: over the relay only the client knows its
    own pids. Absent one, the evaluating process is the driver and reports
    itself. ``hook_event`` is always the evaluating side's answer — it is the
    event actually dispatched, not a claim the payload makes about itself.
    """
    block = payload.get(DRIVER_PAYLOAD_KEY) if isinstance(payload, Mapping) else None
    if isinstance(block, Mapping):
        pid = _positive_int(block.get("pid"))
        ppid = _positive_int(block.get("ppid"))
        if pid is not None:
            resolved = {"pid": pid, "ppid": ppid, "origin": ORIGIN_CLIENT}
            if hook_event:
                resolved["hook_event"] = hook_event
            return resolved
    resolved = {"pid": os.getpid(), "ppid": os.getppid(), "origin": ORIGIN_LOCAL}
    if hook_event:
        resolved["hook_event"] = hook_event
    return resolved


__all__ = [
    "DRIVER_PAYLOAD_KEY",
    "ORIGIN_CLIENT",
    "ORIGIN_LOCAL",
    "collect_driver_process",
    "resolve_driver_process",
]

"""Per-surface reading of one Test Mac verification receipt.

Verification runs named checks that prove different routes into the host:
``connection`` proves SSH -- the route remote exec, resets, and machine
assertions ride -- while ``terminal_bridge`` proves the Terminal.app route
GUI captures ride. The receipt's one overall status and error code collapse
the two, so a host whose SSH works reads as broken when only its Terminal
bridge failed. This names each surface's own outcome and the recovery that
fits it, derived from the recorded check rows rather than stored beside them.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.machine_qa_execution import VERIFICATION_CHECKS


SSH_SURFACE = "ssh"
TERMINAL_BRIDGE_SURFACE = "terminal_bridge"
SURFACE_PASSED = "passed"
SURFACE_FAILED = "failed"
SURFACE_NOT_RUN = "not_run"

_SURFACE_CHECKS = (
    (SSH_SURFACE, VERIFICATION_CHECKS[0]),
    (TERMINAL_BRIDGE_SURFACE, VERIFICATION_CHECKS[1]),
)


def _failed_recovery(surface: str, *, project: str, machine: str) -> str:
    selector = f"--project {project} --machine {machine}"
    if surface == SSH_SURFACE:
        return (
            "Nothing reaches this host until SSH works. Check that the host "
            "is reachable, the capability's host and user are right, and this "
            "machine's ssh-agent holds a key the host authorizes; "
            f"`yoke test-machine exec {selector} -- /usr/bin/true` proves "
            "the route."
        )
    return (
        "SSH still works, so remote exec, resets, and machine assertions do; "
        "Terminal.app captures do not. "
        f"`yoke test-machine bridge-diagnose {selector}` names the blocked "
        "capability."
    )


def verification_surfaces(
    checks: Sequence[Mapping[str, Any]],
    *,
    project: str,
    machine: str,
) -> dict[str, dict[str, Any]]:
    """Return each verified surface's own status, keyed by surface name.

    A surface whose check row is absent reports ``not_run``: the transport
    check failing ends the sequence before the bridge check runs, and a
    receipt from before a check existed never carried it.
    """
    rows = {
        str(check.get("name")): check for check in checks if isinstance(check, Mapping)
    }
    surfaces: dict[str, dict[str, Any]] = {}
    for surface, check_name in _SURFACE_CHECKS:
        row = rows.get(check_name)
        if row is None:
            surfaces[surface] = {"status": SURFACE_NOT_RUN, "check": check_name}
        elif row.get("ok") is True:
            surfaces[surface] = {"status": SURFACE_PASSED, "check": check_name}
        else:
            surfaces[surface] = {
                "status": SURFACE_FAILED,
                "check": check_name,
                "recovery": _failed_recovery(
                    surface,
                    project=project,
                    machine=machine,
                ),
            }
    return surfaces


__all__ = [
    "SSH_SURFACE",
    "SURFACE_FAILED",
    "SURFACE_NOT_RUN",
    "SURFACE_PASSED",
    "TERMINAL_BRIDGE_SURFACE",
    "verification_surfaces",
]

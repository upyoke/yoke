"""Lease-scoped secret staging on an exploratory mission's Test Machine.

Mission preparation creates one owner-only directory for the lease and the
mission teardown removes it, so a secret a walker must hand to a command
through a file never outlives the walk as a loose file. Where the directory
lives and which commands make, probe and remove it belong to the Test
Machine's OS: this module calls only the host control's
``MissionHostOperations`` and owns the refusals.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.qa_mission_scratch import (
    STALE_OWNER_MARKER,
    MissionHostOperations,
    MissionHostStep,
    MissionScratchProbe,
)


_STDERR_EVIDENCE_LIMIT = 400


class MissionScratchUnavailableError(RuntimeError):
    """Refusal naming the scratch path, the failure, and the recovery."""


class MissionScratchStateUnknownError(RuntimeError):
    """The probe never ran, so whether the scratch is gone is unknown."""


def _evidence(step: MissionHostStep) -> str:
    return step.stderr[:_STDERR_EVIDENCE_LIMIT]


def _known(probe: MissionScratchProbe, path: str) -> str:
    """Return present/absent, or refuse when the probe did not run."""
    if probe.state != "unknown":
        return probe.state
    raise MissionScratchStateUnknownError(
        "mission_scratch_state_unknown: could not tell whether the "
        f"secret-staging directory {path} is still on the Test Machine "
        f"({probe.step.command} exited {probe.step.returncode}: "
        f"{_evidence(probe.step) or 'no stderr'}). Restore SSH access to the "
        "host (check its address, listener and authorized key) and re-run "
        "this command; if it still refuses, the operator must check that "
        "path on the host before the machine is handed to anyone else."
    )


def create_mission_scratch(
    control: MissionHostOperations,
    *,
    execution_id: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Create the lease's staging directory and clear the stale owner marker."""
    path = control.mission_scratch_path(execution_id)
    created = control.create_mission_scratch_directory(path, timeout=timeout_seconds)
    if created.returncode != 0:
        raise MissionScratchUnavailableError(
            "mission_scratch_unavailable: could not prepare the "
            f"owner-only secret-staging directory {path} on the Test "
            f"Machine ({created.command} exited {created.returncode}: "
            f"{_evidence(created) or 'no stderr'}). The mission must not stage "
            "secrets without it: restore write access to the scratch root on "
            "the host, or free that path, then re-run the mission."
        )
    stale = control.remove_stale_owner_marker(timeout=timeout_seconds)
    if stale.returncode != 0:
        raise MissionScratchUnavailableError(
            "stale_owner_marker_not_removed: could not delete "
            f"~/{STALE_OWNER_MARKER} on the Test Machine "
            f"({_evidence(stale) or 'no stderr'}). Nothing reads it; restore "
            "the host user's write access to that file, then re-run the "
            "mission."
        )
    return {"scratch_path": path}


def mission_scratch_present(
    control: MissionHostOperations,
    *,
    execution_id: str,
    timeout_seconds: int = 60,
) -> bool:
    """Whether the lease's staging directory is still on the host."""
    path = control.mission_scratch_path(execution_id)
    probe = control.probe_mission_scratch(path, timeout=timeout_seconds)
    return _known(probe, path) == "present"


def remove_mission_scratch(
    control: MissionHostOperations,
    *,
    execution_id: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Remove the lease's staging directory and prove it is gone.

    Removed means the removal exited 0 and the probe proved absence.
    """
    path = control.mission_scratch_path(execution_id)
    stale = control.remove_stale_owner_marker(timeout=timeout_seconds)
    removal = control.remove_mission_scratch_directory(path, timeout=timeout_seconds)
    probe = control.probe_mission_scratch(path, timeout=timeout_seconds)
    absent = _known(probe, path) == "absent"
    return {
        "scratch_path": path,
        "removed": removal.returncode == 0 and absent,
        "removal_exit_code": removal.returncode,
        "removal_stderr": _evidence(removal),
        "stale_owner_marker_removed": stale.returncode == 0,
    }


__all__ = [
    "MissionScratchStateUnknownError",
    "MissionScratchUnavailableError",
    "create_mission_scratch",
    "mission_scratch_present",
    "remove_mission_scratch",
]

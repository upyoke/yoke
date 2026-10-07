"""Lease-scoped secret staging on an exploratory mission's Test Machine.

Mission preparation creates one owner-only directory for the lease and the
mission teardown removes it, so a secret a walker must hand to a command
through a file never outlives the walk as a loose file under ``/tmp``.
Every step is a plain OS command over the host-command route: the Test
Machine needs no Yoke install, and nothing is written to its Yoke home.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from yoke_contracts.qa_mission_scratch import (
    STALE_OWNER_MARKER,
    mission_scratch_create_argv,
    mission_scratch_path,
    mission_scratch_probe_argv,
    mission_scratch_remove_argv,
    mission_scratch_secure_argv,
    stale_owner_marker_remove_argv,
)


_STDERR_EVIDENCE_LIMIT = 400


class MissionScratchHostControl(Protocol):
    """The one host-control capability scratch staging needs."""

    def run_command(
        self,
        argv: Sequence[str],
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> Any: ...


class MissionScratchUnavailableError(RuntimeError):
    """Refusal naming the scratch path, the failure, and the recovery."""


def _evidence(completed: Any) -> str:
    return (getattr(completed, "stderr", "") or "").strip()[:_STDERR_EVIDENCE_LIMIT]


def create_mission_scratch(
    control: MissionScratchHostControl,
    *,
    execution_id: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Create the lease's staging directory and clear the stale owner marker."""
    path = mission_scratch_path(execution_id)
    for argv in (
        mission_scratch_create_argv(path),
        mission_scratch_secure_argv(path),
    ):
        completed = control.run_command(list(argv), timeout=timeout_seconds)
        if int(completed.returncode) != 0:
            evidence = _evidence(completed) or "no stderr"
            raise MissionScratchUnavailableError(
                "mission_scratch_unavailable: could not prepare the "
                f"owner-only secret-staging directory {path} on the Test "
                f"Machine ({' '.join(argv)} exited "
                f"{int(completed.returncode)}: {evidence}). The mission "
                "must not stage secrets without it: restore write access "
                "to the scratch root on the host, or free that path, then "
                "re-run the mission."
            )
    stale = control.run_command(
        stale_owner_marker_remove_argv(), timeout=timeout_seconds
    )
    if int(stale.returncode) != 0:
        raise MissionScratchUnavailableError(
            "stale_owner_marker_not_removed: could not delete "
            f"~/{STALE_OWNER_MARKER} on the Test Machine "
            f"({_evidence(stale) or 'no stderr'}). Nothing reads it; restore "
            "the host user's write access to that file, then re-run the "
            "mission."
        )
    return {"scratch_path": path}


def mission_scratch_present(
    control: MissionScratchHostControl,
    *,
    execution_id: str,
    timeout_seconds: int = 60,
) -> bool:
    """Whether the lease's staging directory is still on the host."""
    probe = control.run_command(
        mission_scratch_probe_argv(mission_scratch_path(execution_id)),
        timeout=timeout_seconds,
    )
    return int(probe.returncode) == 0


def remove_mission_scratch(
    control: MissionScratchHostControl,
    *,
    execution_id: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Remove the lease's staging directory and prove it is gone."""
    path = mission_scratch_path(execution_id)
    stale = control.run_command(
        stale_owner_marker_remove_argv(), timeout=timeout_seconds
    )
    removal = control.run_command(
        mission_scratch_remove_argv(path),
        timeout=timeout_seconds,
    )
    probe = control.run_command(
        mission_scratch_probe_argv(path),
        timeout=timeout_seconds,
    )
    return {
        "scratch_path": path,
        "removed": int(probe.returncode) != 0,
        "removal_exit_code": int(removal.returncode),
        "removal_stderr": _evidence(removal),
        "stale_owner_marker_removed": int(stale.returncode) == 0,
    }


__all__ = [
    "mission_scratch_present",
    "MissionScratchHostControl",
    "MissionScratchUnavailableError",
    "create_mission_scratch",
    "remove_mission_scratch",
]

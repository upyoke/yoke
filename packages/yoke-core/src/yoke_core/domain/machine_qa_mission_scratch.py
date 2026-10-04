"""Lease-scoped secret staging on an exploratory mission's Test Machine.

Mission preparation creates one owner-only directory for the lease and the
mission teardown removes it, so a secret a walker must hand to a command
through a file never outlives the walk as a loose file under ``/tmp``.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence
import json
from pathlib import Path
from yoke_contracts.qa_project_ownership import OWNER_FILE, OWNER_CAPABILITY

from yoke_contracts.qa_mission_scratch import (
    mission_scratch_create_argv,
    mission_scratch_path,
    mission_scratch_probe_argv,
    mission_scratch_remove_argv,
    mission_scratch_secure_argv,
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
) -> str:
    """Create the lease's owner-only staging directory and return its path."""
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
    script = (
        "import json,sys; from pathlib import Path; "
        f"p=Path.home()/'.yoke'/{OWNER_FILE!r}; "
        "p.parent.mkdir(parents=True,exist_ok=True); "
        "previous=json.loads(p.read_text()) if p.exists() else {}; "
        "assert not previous or previous.get('owner')==sys.argv[1], 'qa_project_owner_conflict'; "
        "p.write_text(json.dumps({'owner':sys.argv[1]})); p.chmod(0o600)"
    )
    completed = control.run_command(
        ["python3", "-c", script, execution_id], timeout=timeout_seconds
    )
    if int(completed.returncode) != 0:
        raise MissionScratchUnavailableError(
            "qa_project_owner_unavailable: could not mark this leased host's test "
            "projects; resolve the existing case owner or host write access and "
            "re-prepare the mission. " + _evidence(completed)
        )
    return path


def remove_mission_scratch(
    control: MissionScratchHostControl,
    *,
    execution_id: str,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Remove the lease's staging directory and prove it is gone."""
    path = mission_scratch_path(execution_id)
    # The fresh host need not have installed the product yet. Stage the
    # stdlib-only helper as code, using the same implementation tests import.
    script = Path(__file__).with_name("machine_qa_project_cleanup.py").read_text()
    cleanup = control.run_command(
        ["python3", "-c", script, execution_id, OWNER_FILE, OWNER_CAPABILITY],
        timeout=timeout_seconds,
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
        "project_cleanup_ok": int(cleanup.returncode) == 0,
        "project_cleanup": (
            json.loads(cleanup.stdout)
            if int(cleanup.returncode) == 0
            else {
                "error": _evidence(cleanup),
                "recovery": "Resolve the retirement blocker and retry mission scratch-teardown",
            }
        ),
    }


__all__ = [
    "MissionScratchHostControl",
    "MissionScratchUnavailableError",
    "create_mission_scratch",
    "remove_mission_scratch",
]

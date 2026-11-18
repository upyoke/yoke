"""Mission disk, scratch and continuity operations on a POSIX Test Machine.

macOS, Linux and WSL hosts implement ``MissionHostOperations`` with these
plain OS commands over their ``run_command`` route: the host needs no Yoke
install, and nothing is written to its Yoke home.
"""

from __future__ import annotations

import json
import shlex
from typing import Any, Mapping, Sequence

from yoke_contracts.machine_qa_execution import HOST_TEST_COMMAND
from yoke_contracts.project_command_shell import project_command_shell
from yoke_contracts.qa_mission_scratch import (
    STALE_OWNER_MARKER,
    MissionHostStep,
    MissionScratchProbe,
    mission_scratch_identity,
)


POSIX_MISSION_SCRATCH_ROOT = "/tmp/yoke-qa-mission"
POSIX_MISSION_SCRATCH_MODE = "700"

POSIX_CONTINUITY_PROGRAM = r"""
import hashlib, json, pathlib, sys
failures = []
for name, expected in json.loads(sys.argv[1]).items():
    path = pathlib.Path(name).expanduser()
    try:
        if path.is_symlink() or not path.is_file():
            failures.append({"path": name, "reason": "missing_or_not_regular"})
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            failures.append({"path": name, "reason": "changed"})
    except OSError:
        failures.append({"path": name, "reason": "unreadable"})
print(json.dumps({"ok": not failures, "failures": failures}))
sys.exit(bool(failures))
"""


def posix_mission_scratch_path(execution_id: str) -> str:
    """The lease's scratch directory under the POSIX scratch root."""
    return f"{POSIX_MISSION_SCRATCH_ROOT}/{mission_scratch_identity(execution_id)}"


def posix_scratch_create_argv(path: str) -> list[str]:
    """Create the scratch directory owner-only, tolerating a resumed walk."""
    return ["/bin/mkdir", "-p", "-m", POSIX_MISSION_SCRATCH_MODE, path]


def posix_scratch_secure_argv(path: str) -> list[str]:
    """Force owner-only mode on a scratch directory that already existed."""
    return ["/bin/chmod", POSIX_MISSION_SCRATCH_MODE, path]


def posix_scratch_remove_argv(path: str) -> list[str]:
    """Remove the scratch directory and everything staged inside it."""
    return ["/bin/rm", "-rf", path]


def posix_scratch_probe_argv(path: str) -> list[str]:
    """Exit 0 while the directory exists and 1 once it is gone."""
    return [HOST_TEST_COMMAND, "-e", path]


def posix_stale_owner_marker_remove_argv() -> list[str]:
    """Delete the stale owner marker, then its Yoke home if left empty."""
    return [
        # This argv runs on the POSIX Test Machine, which may be reached
        # from a Windows controller. Its shell belongs to that remote host.
        project_command_shell(platform_name="posix"),
        "-c",
        f'rm -f "$HOME/{STALE_OWNER_MARKER}" || exit 1; '
        'rmdir "$HOME/.yoke" 2>/dev/null; exit 0',
    ]


def _step(control: Any, argv: Sequence[str], timeout: int) -> MissionHostStep:
    completed = control.run_command(list(argv), timeout=timeout)
    return MissionHostStep(
        command=shlex.join(argv),
        returncode=int(completed.returncode),
        stderr=(getattr(completed, "stderr", "") or "").strip(),
    )


class PosixMissionOperations:
    """``MissionHostOperations`` for macOS, Linux and WSL hosts."""

    mission_scratch_root = POSIX_MISSION_SCRATCH_ROOT

    def mission_scratch_path(self, execution_id: str) -> str:
        return posix_mission_scratch_path(execution_id)

    def require_mission_disk_space(self) -> dict[str, Any]:
        from yoke_harness.test_machine_temp_state import require_mission_disk_space

        return require_mission_disk_space(self)

    def create_mission_scratch_directory(
        self, path: str, *, timeout: int = 60
    ) -> MissionHostStep:
        created = _step(self, posix_scratch_create_argv(path), timeout)
        if created.returncode != 0:
            return created
        return _step(self, posix_scratch_secure_argv(path), timeout)

    def remove_mission_scratch_directory(
        self, path: str, *, timeout: int = 60
    ) -> MissionHostStep:
        return _step(self, posix_scratch_remove_argv(path), timeout)

    def probe_mission_scratch(
        self, path: str, *, timeout: int = 60
    ) -> MissionScratchProbe:
        step = _step(self, posix_scratch_probe_argv(path), timeout)
        state = {0: "present", 1: "absent"}.get(step.returncode, "unknown")
        return MissionScratchProbe(state=state, step=step)

    def remove_stale_owner_marker(self, *, timeout: int = 60) -> MissionHostStep:
        return _step(self, posix_stale_owner_marker_remove_argv(), timeout)

    def check_continuity_files(self, fingerprint: Mapping[str, str]) -> dict[str, Any]:
        completed = self.run_command(
            ["python3", "-c", POSIX_CONTINUITY_PROGRAM, json.dumps(dict(fingerprint))],
            timeout=30,
        )
        evidence = json.loads(completed.stdout)
        if int(completed.returncode) != 0 and evidence.get("ok"):
            return {"ok": False, "failures": [{"reason": "check_failed"}]}
        return evidence


__all__ = [
    "POSIX_CONTINUITY_PROGRAM",
    "POSIX_MISSION_SCRATCH_MODE",
    "POSIX_MISSION_SCRATCH_ROOT",
    "PosixMissionOperations",
    "posix_mission_scratch_path",
    "posix_scratch_create_argv",
    "posix_scratch_probe_argv",
    "posix_scratch_remove_argv",
    "posix_scratch_secure_argv",
    "posix_stale_owner_marker_remove_argv",
]

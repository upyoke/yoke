"""Lease-scoped scratch staging for exploratory-mission secret material.

A walker that must hand a token, password, or other secret to a command
through a file writes that file here and nowhere else. The directory is
created owner-only for one mission lease and removed by the mission's
teardown before the walker returns, so a shared test machine never carries a
live-looking credential after the walk ends.

Where the directory lives and how it is made, probed and removed belongs to
the Test Machine's operating system: every host control implements
``MissionHostOperations`` for its OS, and the mission domain calls only that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol


_MISSION_SCRATCH_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Earlier builds left a test-project owner marker in the host's Yoke home.
# Nothing reads it any more; preparation and teardown delete it, and delete
# that home too when the marker was all it held, so a never-installed
# baseline carries no Yoke folder just from being tested.
STALE_OWNER_MARKER = ".yoke/qa-project-owner.json"

# Exit codes a host reports when its probe never ran: SSH lost (255), the
# local timeout fired (124), or the probe command was not found (127).
PROBE_DID_NOT_RUN_EXIT_CODES = (124, 127, 255)


class MissionScratchIdentityError(ValueError):
    """Named refusal for an identity that cannot form a safe scratch path."""


def mission_scratch_identity(execution_id: str) -> str:
    """Return the plan execution id once it is safe as one path segment."""
    identity = str(execution_id)
    if _MISSION_SCRATCH_IDENTITY.fullmatch(identity) is None:
        raise MissionScratchIdentityError(
            "mission scratch requires a plan execution id of 1-128 letters, "
            "digits, dot, dash, or underscore starting alphanumeric; got "
            f"{identity!r}. Pass the execution id the mission dispatch "
            "issued rather than an operator-typed value."
        )
    return identity


@dataclass(frozen=True)
class MissionHostStep:
    """One host command a mission operation ran, as evidence."""

    command: str
    returncode: int
    stderr: str = ""


ScratchState = Literal["present", "absent", "unknown"]


@dataclass(frozen=True)
class MissionScratchProbe:
    """Whether the scratch is on the host; ``unknown`` when the probe failed."""

    state: ScratchState
    step: MissionHostStep


class MissionHostOperations(Protocol):
    """Mission disk, scratch and continuity operations, one per OS."""

    mission_scratch_root: str

    def mission_scratch_path(self, execution_id: str) -> str: ...

    def require_mission_disk_space(self) -> dict[str, Any]: ...

    def create_mission_scratch_directory(
        self, path: str, *, timeout: int = 60
    ) -> MissionHostStep: ...

    def remove_mission_scratch_directory(
        self, path: str, *, timeout: int = 60
    ) -> MissionHostStep: ...

    def probe_mission_scratch(
        self, path: str, *, timeout: int = 60
    ) -> MissionScratchProbe: ...

    def remove_stale_owner_marker(self, *, timeout: int = 60) -> MissionHostStep: ...

    def check_continuity_files(
        self, fingerprint: Mapping[str, str]
    ) -> dict[str, Any]: ...


__all__ = [
    "MissionHostOperations",
    "MissionHostStep",
    "MissionScratchIdentityError",
    "MissionScratchProbe",
    "PROBE_DID_NOT_RUN_EXIT_CODES",
    "STALE_OWNER_MARKER",
    "ScratchState",
    "mission_scratch_identity",
]

"""Lease-scoped scratch staging for exploratory-mission secret material.

A walker that must hand a token, password, or other secret to a command
through a file writes that file here and nowhere else. The directory is
created 0700 for one mission lease and removed by the mission's teardown
before the walker returns, so a shared test machine never carries a
live-looking credential after the walk ends.
"""

from __future__ import annotations

import re

from yoke_contracts.machine_qa_execution import HOST_TEST_COMMAND


MISSION_SCRATCH_ROOT = "/tmp/yoke-qa-mission"
MISSION_SCRATCH_MODE = "700"

_MISSION_SCRATCH_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class MissionScratchIdentityError(ValueError):
    """Named refusal for an identity that cannot form a safe scratch path."""


def mission_scratch_path(execution_id: str) -> str:
    """Return the scratch directory owned by one mission plan execution."""
    identity = str(execution_id)
    if _MISSION_SCRATCH_IDENTITY.fullmatch(identity) is None:
        raise MissionScratchIdentityError(
            "mission scratch requires a plan execution id of 1-128 letters, "
            "digits, dot, dash, or underscore starting alphanumeric; got "
            f"{identity!r}. Pass the execution id the mission dispatch "
            "issued rather than an operator-typed value."
        )
    return f"{MISSION_SCRATCH_ROOT}/{identity}"


def mission_scratch_create_argv(path: str) -> list[str]:
    """Create the scratch directory owner-only, tolerating a resumed walk."""
    return ["/bin/mkdir", "-p", "-m", MISSION_SCRATCH_MODE, path]


def mission_scratch_secure_argv(path: str) -> list[str]:
    """Force owner-only mode on a scratch directory that already existed."""
    return ["/bin/chmod", MISSION_SCRATCH_MODE, path]


def mission_scratch_remove_argv(path: str) -> list[str]:
    """Remove the scratch directory and everything staged inside it."""
    return ["/bin/rm", "-rf", path]


def mission_scratch_probe_argv(path: str) -> list[str]:
    """Exit zero only while the scratch directory still exists."""
    return [HOST_TEST_COMMAND, "-e", path]


__all__ = [
    "MISSION_SCRATCH_MODE",
    "MISSION_SCRATCH_ROOT",
    "MissionScratchIdentityError",
    "mission_scratch_create_argv",
    "mission_scratch_path",
    "mission_scratch_probe_argv",
    "mission_scratch_remove_argv",
    "mission_scratch_secure_argv",
]

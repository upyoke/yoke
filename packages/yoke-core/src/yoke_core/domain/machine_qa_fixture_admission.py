"""Machine QA fixture operations for real machine admission on a test machine.

``fixture.machine-admission-prepare`` runs the installed candidate's own
``machine_qa_admission_host start MODE`` on the controlled machine, so the
exact candidate serves a disposable universe; cleanup runs its ``stop``.
``fixture.machine-admission-state-assert`` proves the universe's actual
people, machines and credentials against the recorded baseline.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.machine_qa_fixture_runtime import (
    RemoteFixtureFailure,
    ServiceCleanup,
)
from yoke_core.domain.machine_qa_fixture_validation_admission import PREPARE

HOST_MODULE = "yoke_core.domain.machine_qa_admission_host"
_START_TIMEOUT_SECONDS = 420
_STOP_TIMEOUT_SECONDS = 120


class MachineQaFixtureAdmissionOperations:
    """Start, prove and stop the installed candidate's admission fixture."""

    def _admission_host(self, *argv: str, timeout: int) -> None:
        """Run one host action; a refusal keeps the host's named reason."""
        command = self._installed_yoke_python("-m", HOST_MODULE, *argv)
        try:
            result = self._run_remote(command, timeout=timeout)
            returncode = int(result.returncode)
        except Exception as exc:
            raise RemoteFixtureFailure(
                f"machine_admission_host_unreachable: {type(exc).__name__}; "
                "restore SSH to the test machine, then rerun the case."
            ) from exc
        if returncode != 0:
            output = str(getattr(result, "stderr", "") or "").strip()
            raise RemoteFixtureFailure(
                output.splitlines()[0]
                if output
                else f"machine_admission_host_failed: exit {returncode}"
            )

    def _machine_admission(self, parameters: Mapping[str, Any]) -> None:
        mode = str(parameters["mode"])
        key = f"machine-admission:{mode}"
        previous = self._services.pop(key, None)
        if previous is not None:
            previous.stop()
        # Register before starting: a start that dies midway still has a
        # server or cluster to remove.
        self._services[key] = ServiceCleanup(
            PREPARE,
            lambda: self._admission_host("stop", mode, timeout=_STOP_TIMEOUT_SECONDS),
        )
        self._admission_host("start", mode, timeout=_START_TIMEOUT_SECONDS)

    def _machine_admission_state(self, parameters: Mapping[str, Any]) -> None:
        self._admission_host(
            "assert",
            str(parameters["mode"]),
            str(parameters["expect"]),
            timeout=_STOP_TIMEOUT_SECONDS,
        )


__all__ = ["HOST_MODULE", "MachineQaFixtureAdmissionOperations"]

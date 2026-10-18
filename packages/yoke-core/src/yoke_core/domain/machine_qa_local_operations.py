"""Adapt credential-local host operations to the client contract."""

from typing import Any
from yoke_core.domain.machine_qa_execution import MachineQaLease


class CoreHostOperations:
    """Adapt the full core execution runtime to the host-operation contract."""

    def __init__(self, execution: MachineQaLease) -> None:
        self._execution = execution
        self.secret_values = tuple(execution.material.secrets.values())

    def capture_screenshot(self) -> Any:
        return self._execution.control.capture_screenshot()

    def check_connection(self) -> Any:
        return self._execution.control.check_connection()

    def check_terminal_bridge(self) -> Any:
        return self._execution.control.check_terminal_bridge()

    def diagnose_terminal_bridge(self) -> Any:
        return self._execution.control.diagnose_terminal_bridge()

    def reach_baseline(self, name: str) -> Any:
        return self._execution.reach_baseline(name)

    def capture_golden_baseline(
        self,
        destination: str,
        *,
        probes_document: str | None = None,
    ) -> Any:
        return self._execution.control.capture_golden_baseline(
            destination,
            probes_document=probes_document,
        )

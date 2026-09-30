"""Machine QA binding for persistent headless Linux hosts."""

from __future__ import annotations

from yoke_core.domain.host_control_runner import TestMachineMaterial
from yoke_core.domain.machine_qa_fixture_operations import (
    MachineQaFixtureOperationRunner,
)
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.ssh_linux_terminal import (
    run_linux_terminal_case,
)
from yoke_harness.test_machine_types import HostActionResult


class SshLinuxHostControl(SshLinuxHostOperations):
    """Use the existing fixture/receipt protocol with SSH and tmux evidence."""

    def __init__(self, material: TestMachineMaterial) -> None:
        self.material = material
        self._pending_terminal_size = (120, 40)
        super().__init__(
            settings=material.settings,
            key_path=material.secret_paths["ssh_private_key"],
            secret_values=tuple(material.secrets.values()),
        )

    def read_text(self, path: str) -> str | None:
        return self.read_remote_text(path)

    def write_text(self, path: str, content: str) -> None:
        self.upload_remote_text(path, content)

    def create_fixture_operation_runner(self) -> MachineQaFixtureOperationRunner:
        return MachineQaFixtureOperationRunner(
            run_remote=self._run,
            upload_text=self.write_text,
            home=self.home,
            path_state=self.path_state,
            prepare_terminal_size=self._set_terminal_size,
            execution_shell="/bin/bash",
        )

    def _set_terminal_size(self, columns: int, rows: int) -> None:
        if not 1 <= columns <= 500 or not 1 <= rows <= 500:
            raise ValueError("terminal size is outside registered bounds")
        self._pending_terminal_size = (columns, rows)

    def _entry_surface(self, value: str) -> str:
        import shlex

        resolved = value.replace("{yoke_bin}", shlex.quote(self.path_state.yoke_bin))
        if "{" in resolved or "}" in resolved:
            raise ValueError("entry surface contains an unregistered placeholder")
        return resolved

    def run_terminal_case(self, **kwargs) -> HostActionResult:
        kwargs["entry_surface"] = self._entry_surface(kwargs["entry_surface"])
        return run_linux_terminal_case(self, size=self._pending_terminal_size, **kwargs)

    def run_terminal_recipe(
        self,
        *,
        entry_surface,
        required_completion,
        config,
        progress_callback=None,
        allowed_operator_urls=(),
    ) -> HostActionResult:
        from yoke_core.domain.ssh_linux_terminal_recipe import execute_linux_recipe

        return execute_linux_recipe(
            self,
            entry_surface=self._entry_surface(entry_surface),
            required_completion=required_completion,
            config=config,
            size=self._pending_terminal_size,
            progress_callback=progress_callback,
        )

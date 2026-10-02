"""Machine-local SSH, PTY, Terminal, screenshot, and shell host_control adapter."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import Any, Mapping, Sequence

from yoke_harness.ssh_mac_transport import (
    SSH_OPTIONS,
    SshMacTransport,
)

from yoke_core.domain import machine_config
from yoke_core.domain.host_control_runner import (
    HostActionResult,
    TestMachineMaterial,
)
from yoke_core.domain.machine_qa_fixture_operations import (
    MachineQaFixtureOperationRunner,
)
from yoke_core.domain.ssh_mac_terminal_legacy import (
    execute_legacy_terminal_case,
)


class SshMacHostControl(SshMacTransport):
    """Approved structured adapter for a project-owned macOS test resource."""

    def __init__(self, material: TestMachineMaterial) -> None:
        self.material = material
        super().__init__(
            settings=material.settings,
            key_path=material.secret_paths["ssh_private_key"],
        )
        self._pending_terminal_size: tuple[int, int] | None = None

    def read_text(self, path: str) -> str | None:
        return self.read_remote_text(path)

    def write_text(self, path: str, content: str) -> None:
        if not self._upload_bytes(path, content.encode("utf-8")):
            raise RuntimeError("host_control file write failed")

    def create_fixture_operation_runner(
        self,
    ) -> MachineQaFixtureOperationRunner:
        """Bind the closed fixture registry to this controlled SSH host."""
        return MachineQaFixtureOperationRunner(
            run_remote=self._run,
            upload_text=self.write_text,
            home=self.home,
            path_state=self.path_state,
            prepare_terminal_size=self._set_terminal_size,
        )

    def _set_terminal_size(self, columns: int, rows: int) -> None:
        if not 1 <= columns <= 500 or not 1 <= rows <= 500:
            raise ValueError("terminal size is outside the registered bounds")
        self._pending_terminal_size = (columns, rows)

    def _resolve_entry_surface(self, entry_surface: str) -> str:
        placeholder = "{yoke_bin}"
        if placeholder not in entry_surface:
            if "{" in entry_surface or "}" in entry_surface:
                raise ValueError("entry surface contains an unregistered placeholder")
            return entry_surface
        resolved = entry_surface.replace(
            placeholder,
            shlex.quote(self.path_state.yoke_bin),
        )
        if "{" in resolved or "}" in resolved:
            raise ValueError("entry surface contains an unregistered placeholder")
        return resolved

    def run_terminal_case(
        self,
        *,
        entry_surface: str,
        required_completion: str,
        steps: Sequence[Mapping[str, Any]],
        capture_checkpoints: Sequence[str],
    ) -> HostActionResult:
        return execute_legacy_terminal_case(
            self._run,
            entry_surface=self._resolve_entry_surface(entry_surface),
            required_completion=required_completion,
            steps=steps,
            capture_checkpoints=capture_checkpoints,
            evidence_parent=machine_config.yoke_home() / "qa-host-control",
        )

    def run_terminal_recipe(
        self,
        *,
        entry_surface: str,
        required_completion: str,
        config: Mapping[str, Any],
        progress_callback: Callable[[], None] | None = None,
        allowed_operator_urls: Sequence[str] = (),
    ) -> HostActionResult:
        from yoke_core.domain.ssh_mac_terminal_recipe import (
            execute_terminal_recipe,
        )

        from yoke_core.domain.ssh_mac_browser_approval import (
            approve_machine_in_safari,
        )

        terminal_size = self._pending_terminal_size
        self._pending_terminal_size = None
        return execute_terminal_recipe(
            self._run,
            upload_bytes=self._upload_bytes,
            entry_surface=self._resolve_entry_surface(entry_surface),
            required_completion=required_completion,
            config=config,
            evidence_parent=machine_config.yoke_home() / "qa-host-control",
            secret_values=tuple(self.material.secrets.values()),
            terminal_size=terminal_size,
            progress_callback=progress_callback,
            allowed_operator_urls=tuple(allowed_operator_urls),
            approve_browser=lambda url, code: approve_machine_in_safari(
                self._run, verification_url=url, user_code=code
            ),
        )


__all__ = [
    "SSH_OPTIONS",
    "SshMacHostControl",
]

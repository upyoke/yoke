"""Windows OpenSSH transport into a persistent WSL2 Linux test home."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
import shlex

from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT
from yoke_contracts.machine_qa_failures import SSH_UNAVAILABLE, HostControlLocalError
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.ssh_linux_terminal import diagnose_linux_terminal
from yoke_harness.ssh_machine_screenshot import capture_desktop as capture_xfce
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.ssh_native_windows_host_operations import (
    SshNativeWindowsHostOperations,
)
from yoke_harness.native_windows.terminal import run_native_terminal_case
from yoke_harness.native_windows.terminal import WindowsTerminal
from yoke_harness.native_windows.console import verify_console
from yoke_harness.native_windows.desktop import capture_desktop, desktop_script
from yoke_harness.native_windows.transport import WindowsTransport
from yoke_harness.native_windows.yoke_python import (
    opens_identity_page,
    yoke_python_command,
)

__all__ = [
    "SshWindowsHostOperations",
    "SshNativeWindowsHostOperations",
    "run_native_terminal_case",
    "WindowsTerminal",
    "desktop_script",
    "opens_identity_page",
    "yoke_python_command",
]
from yoke_contracts.windows_wsl_command import (
    windows_wsl_command,
    windows_wsl_input,
    windows_wsl_powershell,
)


class SshWindowsHostOperations(SshLinuxHostOperations):
    """Reuse Linux golden archives, probes, resets and tmux inside WSL2.

    Windows itself is outside the reset boundary. The golden path names an
    absolute Linux path outside the WSL user's home. Windows SSH credentials
    and the WSL registration survive each Linux home restore.
    """

    @cached_property
    def wsl_desktop_session(self):
        return self._settings.get("wsl_desktop_session", "xfce")

    @cached_property
    def windows_host(self):
        """Use the same SSH account and trust settings without entering WSL."""
        return WindowsTransport(
            settings=self._settings,
            key_path=self._key_path,
            secret_values=self.secret_values,
        )

    def run_command(self, argv, *, required_session_context=None, timeout=60):
        if required_session_context == GUI_SESSION_CONTEXT and self.wsl_desktop_session == "windows":
            if not argv or not str(argv[0]):
                raise ValueError("host_control command requires a non-empty executable")
            result = desktop_script(
                self.windows_host, windows_wsl_powershell(shlex.join(argv)), timeout=timeout
            )
            result.desktop_session = "windows_console"
            return result
        return super().run_command(
            argv, required_session_context=required_session_context, timeout=timeout
        )

    def capture_screenshot(self, *, focused_window=False):
        if self.wsl_desktop_session == "windows":
            result = capture_desktop(self.windows_host, focused_window=focused_window)
            if not result.ok:
                return result
            # The receipt must name the WSL machine its contract was issued for.
            return HostActionResult(
                True,
                {**result.evidence, "os": "wsl", "desktop_session": "windows_console"},
                result.error_code,
            )
        return super().capture_screenshot(focused_window=focused_window)

    def diagnose_terminal_bridge(self):
        return diagnose_linux_terminal(self, capture_screenshot=lambda: capture_xfce(self))

    def check_terminal_bridge(self):
        if "wsl_desktop_session" in self._settings:
            return verify_console(self.windows_host, self.diagnose_terminal_bridge, wsl=True)
        return self.diagnose_terminal_bridge()

    def _ssh_argv(self, command: str) -> list[str]:
        return super()._ssh_argv(windows_wsl_command(command))

    def _run(
        self,
        command: str,
        *,
        input_text: str | None = None,
        timeout: int = 60,
        debug_log: Path | None = None,
    ):
        reader, framed_input = windows_wsl_input(command, input_text)
        return super()._run(
            reader,
            input_text=framed_input,
            timeout=timeout,
            debug_log=debug_log,
        )

    def _host_facts(self):
        try:
            facts = super()._host_facts()
        except HostControlLocalError as exc:
            if exc.code == SSH_UNAVAILABLE:
                raise
            raise HostControlLocalError(
                code="windows_wsl_user_required",
                phase="host_facts_ssh",
                detail="Windows Test Machines require Python 3 and a non-root Linux default user in the SSH account's default WSL distro.",
                recovery_hint="Install Python 3 inside that distro and set [user] default in /etc/wsl.conf; restart WSL and retry.",
            ) from exc
        result = self._run("cat /proc/sys/kernel/osrelease", timeout=20)
        if result.returncode or "wsl2" not in result.stdout.lower():
            raise HostControlLocalError(
                code="windows_wsl2_required",
                phase="host_facts_ssh",
                detail="The Windows SSH user's default distro must run WSL2.",
                recovery_hint="Install Ubuntu under the Windows SSH account, run wsl --set-version DISTRO 2, and set its non-root default user before retrying.",
            )
        return facts

    def check_connection(self) -> HostActionResult:
        result = super().check_connection()
        return HostActionResult(
            result.ok,
            {**result.evidence, "os": "wsl"},
            result.error_code,
        )

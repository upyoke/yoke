"""Windows OpenSSH transport into a persistent WSL2 Linux test home."""

from __future__ import annotations

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.test_machine_types import HostActionResult
from yoke_harness.windows_wsl_command import windows_wsl_command


class SshWindowsHostOperations(SshLinuxHostOperations):
    """Reuse Linux golden archives, probes, resets and tmux inside WSL2.

    Windows itself is outside the reset boundary. The golden path names an
    absolute Linux path outside the WSL user's home. Windows SSH credentials
    and the WSL registration survive each Linux home restore.
    """

    def _ssh_argv(self, command: str) -> list[str]:
        return super()._ssh_argv(windows_wsl_command(command))

    def _host_facts(self):
        try:
            facts = super()._host_facts()
        except HostControlLocalError as exc:
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
            {**result.evidence, "os": "windows", "execution_context": "wsl2"},
            result.error_code,
        )

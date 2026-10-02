"""Machine QA's existing Linux operations reached through Windows OpenSSH."""

from yoke_core.domain.ssh_linux_host_control import SshLinuxHostControl
from yoke_harness.ssh_windows_host_operations import SshWindowsHostOperations


class SshWindowsHostControl(SshWindowsHostOperations, SshLinuxHostControl):
    """Keep fixture, terminal and receipt protocols inside the WSL test home."""

    def __init__(self, material):
        super().__init__(material)
        self._desktop_project = material.project
        self._desktop_settings = material.settings

"""Machine QA's existing Linux operations reached through Windows OpenSSH."""

from yoke_core.domain.ssh_linux_host_control import SshLinuxHostControl
from yoke_contracts.runtime_ports.ssh_windows_host_operations import get_ssh_windows_host_operations



SshWindowsHostOperations = get_ssh_windows_host_operations().SshWindowsHostOperations

class SshWindowsHostControl(SshWindowsHostOperations, SshLinuxHostControl):
    """Keep fixture, terminal and receipt protocols inside the WSL test home."""

"""OS selection for the existing credential-local Machine QA adapter."""

from __future__ import annotations

from yoke_contracts.machine_config.test_machine import validate_test_machine_os
from yoke_core.domain.host_control_runner import (
    register_host_control_factory,
    TestMachineMaterial,
)


def host_control_for(material: TestMachineMaterial):
    os_name = validate_test_machine_os(material.settings.get("os"))
    if os_name == "macos":
        from yoke_core.domain.ssh_mac_host_control import SshMacHostControl

        return SshMacHostControl(material)
    from yoke_core.domain.ssh_linux_host_control import SshLinuxHostControl

    return SshLinuxHostControl(material)


def register_test_machine_host_control() -> None:
    """Register the OS-selecting factory before materializing a host contract."""
    register_host_control_factory(host_control_for)

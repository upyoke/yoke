"""SSH-backed implementation of the host-operation contract for a macOS box.

One class implements every operation a person can run against a macOS SSH test
machine -- verify, reset, capture a golden baseline, diagnose the terminal
bridge -- because they share a transport, a credential, and a lease, and
splitting them by operation would give four adapters four chances to disagree
about what the same host is.
"""

from __future__ import annotations
from yoke_harness.ssh_mac_transport import SshMacTransport
from yoke_harness.ssh_host_baselines import SshHostBaselines


class SshMacHostOperations(SshHostBaselines, SshMacTransport):
    """Credential-owning control for every operator-run macOS SSH operation."""

    def capture_screenshot(self):
        from yoke_harness.ssh_machine_screenshot import capture_desktop

        return capture_desktop(self)

    def __init__(
        self,
        *,
        settings: dict[str, str],
        key_path: str,
        secret_values: tuple[str, ...],
    ) -> None:
        self.secret_values = secret_values
        super().__init__(
            settings=settings, key_path=key_path, secret_values=secret_values
        )


__all__ = ["SshMacHostOperations"]

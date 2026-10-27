"""Help text for the operator-run test-machine host operations."""

from __future__ import annotations

_RESET_DESCRIPTION = (
    "Restore the declared baseline and clear owned Yoke/harness temporary artifacts. "
    "Preserve the golden, live browser identities, restored home and live mission scratch. "
    "The receipt reports temp_cleanup.freed_bytes; cleanup failures refuse with recovery."
)
_VERIFY_DESCRIPTION = (
    "Check the SSH connection and the Terminal bridge, then reach each declared "
    "baseline, which restores it and clears owned Yoke/harness temporary artifacts. "
    "A failed connection stops the run; any other failed step is recorded and the "
    "run continues. The first failure sets the result."
)
_SCREENSHOT_DESCRIPTION = (
    "Capture the actual desktop as a validated PNG under the machine lease. "
    "The receipt stores a durable QA artifact handle; artifact_path names a private local PNG. "
    "macOS needs the test user's unlocked Terminal.app session and Screen Recording grant; "
    "Linux reuses one XFCE Xorg display or starts it with the registered desktop_password. "
    "GTK uses GDK_BACKEND=x11 so Windows WSLg cannot redirect it off that display. "
    "A reused blank desktop restarts once unless an RDP client or another login owns it; "
    "desktop_session reports started/reused/restarted. Persistent blank frames report "
    "~/.xsession-errors and /var/log/xrdp-sesman.log evidence. "
    "Provision XFCE using .yoke/docs/verification/test-machines/linux-host-provisioning.md; "
    "repair the registered fixture secret or xrdp/XFCE and rerun if startup refuses. "
    "Windows captures that same XFCE browser display inside the SSH user's default WSL2 distro. "
    "Close credentials/private windows when the case requires it. Failed or blank capture exits nonzero."
)

HOST_OPERATION_DESCRIPTIONS: dict[str, str] = {
    "reset": _RESET_DESCRIPTION,
    "verify": _VERIFY_DESCRIPTION,
    "screenshot": _SCREENSHOT_DESCRIPTION,
}

__all__ = ["HOST_OPERATION_DESCRIPTIONS"]

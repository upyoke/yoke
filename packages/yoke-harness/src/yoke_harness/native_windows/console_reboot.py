"""Recover a signed-out native Windows console under the reset lease."""

import time
from datetime import datetime, timedelta, timezone

from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.console import PROBE_TIMEOUT, SIGNED_OUT_PROBE, probe_console

WAIT_SECONDS = 600
POLL_SECONDS = 10
SSH_TIMEOUT = 20
BOOT_TOLERANCE = timedelta(seconds=30)
# Windows PowerShell uses .NET Framework, which lacks Environment.TickCount64.
BOOT_TIME = r"""
Add-Type @'
using System.Runtime.InteropServices;
public static class YokeBootClock {
 [DllImport("kernel32.dll")] public static extern ulong GetTickCount64();
}
'@
[DateTime]::UtcNow.AddMilliseconds(-[double][YokeBootClock]::GetTickCount64()).ToString('o')
"""
REBOOT = r"""& "$env:SystemRoot\System32\shutdown.exe" /r /t 0 /d p:4:1
exit $LASTEXITCODE
"""


def _boot_time(control, timeout):
    result = control._run(BOOT_TIME, timeout=timeout)
    if result.returncode or result.stderr.strip():
        return None
    try:
        boot = datetime.fromisoformat(result.stdout.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return boot if boot.tzinfo == timezone.utc else None


def _failure(console, diagnostic, recovery):
    return HostActionResult(
        False,
        {**console.evidence, "diagnostic": diagnostic, "recovery": recovery},
        console.error_code,
    )


def restore_console(control):
    console = probe_console(control, set_resolution=True)
    if console.ok:
        return HostActionResult(True, {"windows_console": console.evidence})
    try:
        signed_out = control._run(SIGNED_OUT_PROBE, timeout=SSH_TIMEOUT)
    except (OSError, RuntimeError):
        return console
    if (
        signed_out.returncode
        or signed_out.stderr.strip()
        or signed_out.stdout.strip() != "YOKE_WINDOWS_SIGNED_OUT"
    ):
        return console

    before = _boot_time(control, SSH_TIMEOUT)
    if before is None:
        return _failure(
            console, "reboot_refused",
            "Check the Windows boot-time probe over the lab account's SSH connection and retry.",
        )
    result = control._run(REBOOT, timeout=SSH_TIMEOUT)
    if result.returncode not in (0, 124, 255):
        return _failure(
            console, "reboot_refused",
            "Check shutdown.exe and the lab account's SeShutdownPrivilege, then retry reset.",
        )

    announce_designed_wait(
        "native Windows reboot and autologon",
        max_wait_seconds=WAIT_SECONDS, cadence=poll_every(POLL_SECONDS),
    )
    started = time.monotonic()
    deadline = started + WAIT_SECONDS
    after = None
    while (remaining := deadline - time.monotonic()) > 0:
        if after is None:
            observed = _boot_time(control, min(SSH_TIMEOUT, remaining))
            if observed is not None and observed > before + BOOT_TOLERANCE:
                after = observed
        if after is not None and deadline - time.monotonic() >= PROBE_TIMEOUT:
            ready = probe_console(control, set_resolution=True, retry=True)
            elapsed = time.monotonic() - started
            if ready.ok and elapsed <= WAIT_SECONDS:
                return HostActionResult(True, {
                    "windows_console": ready.evidence,
                    "console_reboot": {
                        "boot_before": before.isoformat(),
                        "boot_after": after.isoformat(),
                        "elapsed_s": round(elapsed, 1),
                    },
                })
        time.sleep(max(0, min(POLL_SECONDS, deadline - time.monotonic())))

    if after is None:
        return _failure(
            console, "reboot_not_observed",
            "Check the VM power state and the lab account's SSH access, then retry reset.",
        )
    return _failure(
        console, "console_not_ready_after_reboot",
        "Check autologon in the VM console and repair Windows desktop provisioning before retrying.",
    )

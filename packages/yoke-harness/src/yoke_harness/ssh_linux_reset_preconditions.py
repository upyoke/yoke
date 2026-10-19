"""Linux capture/reset admission: sealed probes, Chromium and the desktop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_harness.ssh_linux_browser_approval import quit_desktop_chromium
from yoke_harness.ssh_mac_baseline_probes import (
    GOLDEN_PROBES_SUFFIX,
    parse_baseline_probes,
)
from yoke_harness.test_machine_types import HostActionResult

# Shared by the read-only admission call and the final check before teardown.
from yoke_harness import linux_desktop_state

DESKTOP_PROGRAM = (
    Path(linux_desktop_state.__file__)
    .read_text()
    .replace("from __future__ import annotations", "")
)


def reset_preflight(control: Any, destination: str) -> HostActionResult:
    """Read and parse the sealed probes before any cleanup."""
    try:
        document = control.read_remote_text(destination + GOLDEN_PROBES_SUFFIX)
    except RuntimeError:
        return HostActionResult(
            False,
            {"recovery": "Repair the sealed baseline probes file access, then retry."},
            "baseline_probes_unavailable",
        )
    try:
        probes = parse_baseline_probes(document)
    except ValueError:
        return HostActionResult(
            False,
            {
                "recovery": "Repair the sealed baseline probes document before resetting."
            },
            "baseline_probes_invalid",
        )
    return HostActionResult(True, {"sealed_probe_count": len(probes)})


def archive_admission(
    control: Any, operation: str, destination: str
) -> HostActionResult:
    """Admit a capture or reset: read the sealed probes, then quit desktop Chromium.

    Chromium writes its cookie store when it quits, so a capture taken while it
    runs can miss the newest sign-in, and a running Chromium would write its
    in-memory state back over a restored home. It is asked to quit, never killed.
    """
    if operation == "reset":
        preflight = reset_preflight(control, destination)
        if not preflight.ok:
            return preflight
    quit_apps = quit_desktop_chromium(control)
    if not quit_apps.ok:
        return quit_apps
    return HostActionResult(True, quit_apps.evidence)

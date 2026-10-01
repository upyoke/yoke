"""Machine-local Linux checkout and WSL service readiness checks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from yoke_harness.wsl import is_wsl, systemd_running
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


def hc_windows_mount_checkout(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    check_id, name = "HC-windows-mount-checkout", "Checkout on a Windows mount"
    if not sys.platform.startswith("linux"):
        rec.record(check_id, name, "N/A", "This check applies only on Linux.")
        return
    root = _resolve_repo_root()
    if not root:
        rec.record(check_id, name, "N/A", "No project checkout is available.")
        return
    path = str(Path(root).resolve())
    if re.match(r"^/mnt/[a-zA-Z](?:/|$)", path):
        rec.record(
            check_id,
            name,
            "WARN",
            f"{path} is on a Windows drive. Move the checkout into the Linux "
            "filesystem, for example ~/projects, and bind that checkout to Yoke.",
        )
    else:
        rec.record(check_id, name, "PASS", f"Checkout is outside /mnt/<drive>: {path}")


def hc_wsl_systemd(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    check_id, name = "HC-wsl-systemd", "WSL systemd readiness"
    if not is_wsl():
        rec.record(check_id, name, "N/A", "This machine is not running WSL on Linux.")
        return
    try:
        running = systemd_running()
    except OSError as exc:
        rec.record(
            check_id,
            name,
            "WARN",
            f"wsl_pid1_unreadable: {exc}; restore /proc access and rerun doctor.",
        )
        return
    if running:
        rec.record(check_id, name, "PASS", "WSL is running systemd as PID 1.")
    else:
        rec.record(
            check_id,
            name,
            "WARN",
            "WSL is not running systemd as PID 1. Run yoke wsl setup, then "
            "run wsl --shutdown from Windows and reopen Ubuntu.",
        )

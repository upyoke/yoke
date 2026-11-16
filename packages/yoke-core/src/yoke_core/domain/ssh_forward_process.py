"""Foreground OpenSSH custody without Unix daemonization or console inheritance."""

from __future__ import annotations

import psutil
import subprocess
import tempfile
import time
from typing import Sequence

from yoke_contracts.platform_process import spawn_group, stop_group
from yoke_core.domain.ssh_identity import validate_identity


def start_forward(argv: Sequence[str], *, host: str, port: int, timeout: float) -> None:
    """Return once SSH is listening; terminate its tree before reporting failure.

    The group outlives this CLI. Another client can discover and adopt the same
    forward; closing this process must not drop that client's leased connection.
    stderr uses a file so a ProxyCommand child cannot keep a capture pipe open.
    """
    validate_identity(argv)
    with tempfile.TemporaryFile() as errors:
        try:
            handle = spawn_group(
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=errors,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.seek(0)
            detail = errors.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"ssh tunnel start could not run: {exc}; {detail}; check OpenSSH and the "
                "configured identity, then retry"
            ) from exc
        process = handle.process
        try:
            deadline = time.monotonic() + timeout
            while True:
                rc = process.poll()
                if rc is not None:
                    errors.seek(0)
                    detail = errors.read().decode("utf-8", errors="replace").strip()
                    raise RuntimeError(
                        f"ssh tunnel start failed (rc={rc}): {detail}; "
                        "check SSH authentication and forwarding settings, then retry"
                    )
                try:
                    listeners = psutil.Process(handle.pid).net_connections(kind="tcp")
                    if any(entry.status == psutil.CONN_LISTEN and entry.laddr.port == port
                           and entry.laddr.ip in {host, "0.0.0.0", "::"} for entry in listeners):
                        return
                except psutil.NoSuchProcess:
                    continue
                except psutil.AccessDenied as exc:
                    raise RuntimeError(
                        "ssh_tunnel_inspection_failed: cannot inspect the spawned "
                        "forward; run as its owner and retry"
                    ) from exc
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"ssh tunnel start timed out after {timeout}s; "
                        "check SSH reachability and the local port, then retry"
                    )
                time.sleep(0.05)
        except BaseException:
            stop_group(handle, timeout=1.0)
            raise

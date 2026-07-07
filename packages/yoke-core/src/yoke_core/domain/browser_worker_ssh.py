"""SSH command builders + small output helpers for ``browser_worker``.

Pure builders that return ``argv`` lists for ``ssh`` invocations, plus the
``pgrep``-based tunnel-PID resolver and the tiny stdout/stderr/timestamp
helpers consumed by both the SSH path and the command callables. The
parent ``browser_worker`` module re-exports every public name so tests
can patch them via ``mock.patch.object(browser_worker, ...)``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from yoke_core.domain.browser_worker import RemoteConfig


# ---------------------------------------------------------------------------
# SSH command builders (kept pure so tests can assert argv)
# ---------------------------------------------------------------------------

def _ssh_base(cfg: "RemoteConfig", *, connect_timeout: int) -> List[str]:
    cmd = ["ssh"]
    if cfg.key_path:
        cmd += ["-i", cfg.key_path]
    cmd += [
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={connect_timeout}",
    ]
    return cmd


def _ssh_target(cfg: "RemoteConfig") -> str:
    return f"{cfg.user}@{cfg.host}"


def _ssh_exec(
    cfg: "RemoteConfig",
    remote_cmd: str,
    *,
    connect_timeout: int = 10,
) -> List[str]:
    return [*_ssh_base(cfg, connect_timeout=connect_timeout), _ssh_target(cfg), remote_cmd]


def _ssh_tunnel_argv(
    cfg: "RemoteConfig",
    *,
    local_port: int,
    remote_port: int,
    connect_timeout: int = 10,
) -> List[str]:
    return [
        *_ssh_base(cfg, connect_timeout=connect_timeout),
        "-f",
        "-N",
        "-L",
        f"{local_port}:127.0.0.1:{remote_port}",
        _ssh_target(cfg),
    ]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _emit(msg: str) -> None:
    sys.stdout.write(msg)
    if not msg.endswith("\n"):
        sys.stdout.write("\n")


def _err(msg: str) -> None:
    sys.stderr.write(msg)
    if not msg.endswith("\n"):
        sys.stderr.write("\n")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tunnel PID lookup
# ---------------------------------------------------------------------------

def _find_tunnel_pid(local_port: int, remote_port: int, host: str) -> Optional[int]:
    """Return the PID of the ``ssh -f -N -L`` process we just forked."""
    if not shutil.which("pgrep"):
        return None
    pattern = rf"ssh.*-L.*{local_port}:127\.0\.0\.1:{remote_port}.*{re.escape(host)}"
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            return int(line)
        except ValueError:
            continue
    return None

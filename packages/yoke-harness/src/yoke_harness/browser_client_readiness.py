"""Wait for a launched browser daemon to report a healthy endpoint.

A daemon that never becomes ready has to say why: it may have exited on
startup, written a state file for a different process, or come up with an
endpoint that does not answer. Each of those reads differently to whoever is
looking, so the wait keeps the last reason and reports it with the daemon's
own stderr rather than a bare timeout.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict


READINESS_ATTEMPTS = 10


def launch_daemon(command: list[str], env: dict[str, str], log_file: Path):
    """Start outside the caller's terminal process group and standard input.

    Short-lived command shells may tear down their entire process group on
    exit, after the daemon has already answered its first health request.
    """
    isolation = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        with log_file.open("w", encoding="utf-8") as stderr_log:
            return subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_log,
                env=env,
                **isolation,
            )
    except OSError as exc:
        raise RuntimeError(
            f"browser daemon could not start independently of the caller: {exc}. "
            "Check the Node executable and browser runtime permissions, then "
            "run `yoke qa browser setup` again."
        ) from None


def _client():
    # Lazy, like the sibling action module: it keeps the parent module's
    # DaemonState and health-probe patch seams intact for callers and tests.
    from yoke_harness import browser_client

    return browser_client


def wait_for_daemon_ready(proc, log_file: Path) -> Dict[str, Any]:
    """Return the started-daemon report, or raise with what went wrong."""
    client = _client()
    last_readiness_error = "state file not ready"
    for _ in range(READINESS_ATTEMPTS):
        current = client.DaemonState.load()
        if current and current.pid != proc.pid:
            last_readiness_error = (
                f"state pid {current.pid} does not match launched pid {proc.pid}"
            )
        elif current and current.health == "healthy":
            try:
                client._probe_daemon_health(current, timeout=1)
            except RuntimeError as exc:
                last_readiness_error = str(exc)
            else:
                return {
                    "status": "started",
                    "endpoint": current.endpoint,
                    "pid": proc.pid,
                }
        try:
            proc.wait(timeout=0)
            raise RuntimeError(
                f"daemon process exited unexpectedly\n{_stderr(log_file)}"
            )
        except subprocess.TimeoutExpired:
            pass
        client.time.sleep(1)

    proc.kill()
    detail = f"last readiness error: {last_readiness_error}"
    stderr_content = _stderr(log_file)
    if stderr_content:
        detail += f"\ndaemon stderr:\n{stderr_content}"
    raise RuntimeError(
        f"timeout waiting for browser daemon health endpoint to become ready\n{detail}"
    )


def _stderr(log_file: Path) -> str:
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


__all__ = ["READINESS_ATTEMPTS", "launch_daemon", "wait_for_daemon_ready"]

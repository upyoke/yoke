"""Wait for a launched browser daemon to report a healthy endpoint.

A daemon that never becomes ready has to say why: it may have exited on
startup, written a state file for a different process, or come up with an
endpoint that does not answer. Each of those reads differently to whoever is
looking, so the wait keeps the last reason and reports it with the daemon's
own log rather than a bare timeout.

Both the harness and core daemon starts launch and wait through this module,
so a cold start is judged by one deadline and one log everywhere.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional


#: The daemon's combined stdout and stderr, in the browser runtime home. Its
#: stdout carries the startup phase lines (``Launching Chromium``, ``Browser
#: launched.``, ``Daemon listening``), so the log names how far a slow or
#: stalled start got.
DAEMON_LOG_NAME = ".daemon.log"

#: How long a live, still-starting daemon may take to report healthy. A warm
#: start answers in under a second, but a cold start on a loaded machine —
#: first load of the runtime's modules plus a first Chromium exec — was
#: measured at 12.9s, past the ten one-second polls this replaced, which
#: killed the daemon mid-launch on every attempt. The wait returns the moment
#: the daemon is healthy or exits, so only a daemon that is alive and still
#: starting ever uses the whole budget.
READINESS_TIMEOUT_SECONDS = 60.0
READINESS_POLL_SECONDS = 0.25


def launch_daemon(command: list[str], env: dict[str, str], log_file: Path):
    """Start outside the caller's terminal process group and standard input.

    Short-lived command shells may tear down their entire process group on
    exit, after the daemon has already answered its first health request.
    """
    isolation = (
        {
            "creationflags": subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        }
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        with log_file.open("w", encoding="utf-8") as daemon_log:
            return subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=daemon_log,
                stderr=subprocess.STDOUT,
                env=env,
                **isolation,
            )
    except OSError as exc:
        raise RuntimeError(
            f"browser daemon could not start independently of the caller: {exc}. "
            "Check the Node executable and browser runtime permissions, then "
            "run `yoke qa browser setup` again."
        ) from None


def start_daemon(
    command: list[str], env: dict[str, str], runtime_dir: Path, **wait_seams: Any
) -> Dict[str, Any]:
    """Launch the daemon logging into ``runtime_dir`` and wait until it is ready.

    ``wait_seams`` pass through to :func:`wait_for_daemon_ready`.
    """
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_file = runtime_dir / DAEMON_LOG_NAME
    proc = launch_daemon(command, env, log_file)
    return wait_for_daemon_ready(proc, log_file, **wait_seams)


def _client():
    # Lazy, like the sibling action module: it keeps the parent module's
    # DaemonState and health-probe patch seams intact for callers and tests.
    from yoke_harness import browser_client

    return browser_client


def wait_for_daemon_ready(
    proc,
    log_file: Path,
    *,
    load_state: Optional[Callable[[], Any]] = None,
    probe_health: Optional[Callable[[Any], None]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Optional[Callable[[float], None]] = None,
) -> Dict[str, Any]:
    """Return the started-daemon report, or raise with what went wrong.

    ``load_state`` and ``probe_health`` default to the harness client's; the
    core client passes its own so its state-file seam stays its own.
    """
    if load_state is None or probe_health is None or sleep is None:
        client = _client()
        load_state = load_state or client.DaemonState.load
        probe_health = probe_health or (
            lambda state: client._probe_daemon_health(state, timeout=1)
        )
        sleep = sleep or client.time.sleep
    deadline = clock() + READINESS_TIMEOUT_SECONDS
    last_readiness_error = "state file not written yet"
    while True:
        current = load_state()
        if current and current.pid != proc.pid:
            last_readiness_error = (
                f"state pid {current.pid} does not match launched pid {proc.pid}"
            )
        elif current and current.health == "healthy":
            try:
                probe_health(current)
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
            log_content = _daemon_log(log_file)
            raise RuntimeError(
                f"daemon process exited unexpectedly\n{log_content}"
                f"{_exit_recovery(log_content)}"
            )
        except subprocess.TimeoutExpired:
            pass
        if clock() >= deadline:
            break
        sleep(READINESS_POLL_SECONDS)

    proc.kill()
    proc.wait()
    log_content = _daemon_log(log_file)
    raise RuntimeError(
        f"browser daemon (pid {proc.pid}) was still starting after "
        f"{READINESS_TIMEOUT_SECONDS:g}s and was stopped; "
        f"last readiness error: {last_readiness_error}\n"
        f"daemon log ({log_file}) — its last line is the startup phase it "
        f"reached:\n{log_content or '(empty: the daemon wrote nothing)'}\n"
        "Recovery: a start stalled at `Launching Chromium` points at the "
        "browser binary or its profile; check it with `yoke qa browser "
        "status`, then retry with `yoke qa browser setup`."
    )


def _exit_recovery(log_content: str) -> str:
    if "EADDRINUSE" not in log_content:
        return ""
    return (
        "\nRecovery: another process holds the daemon port. Name it with "
        "`lsof -nP -iTCP -sTCP:LISTEN`; a browser daemon left by another "
        "runtime home or a test run exits on its own idle timeout, so stop it "
        "or wait it out, then retry with `yoke qa browser setup`."
    )


def _daemon_log(log_file: Path) -> str:
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


__all__ = [
    "DAEMON_LOG_NAME",
    "READINESS_POLL_SECONDS",
    "READINESS_TIMEOUT_SECONDS",
    "launch_daemon",
    "start_daemon",
    "wait_for_daemon_ready",
]

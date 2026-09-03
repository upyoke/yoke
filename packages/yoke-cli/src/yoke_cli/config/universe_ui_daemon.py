"""Lifecycle for the detached machine-local universe UI daemon.

``yoke ui up`` starts the loopback-only, token-gated server in a process
that outlives the terminal that asked for it; ``yoke ui status`` reports
whether that process is serving and where; ``yoke ui down`` stops it.

Both start paths — a launchd user agent on macOS, a detached child
elsewhere — run the identical ``yoke ui serve-process`` entrypoint, and
that serving process publishes its own record. So status and stop read
one shape regardless of which supervisor brought the view up, and a
daemon launchd restarted after a reboot is indistinguishable from one
this command started.

File custody (token, record, log) lives in
:mod:`yoke_cli.config.universe_ui_daemon_state`; launchd specifics live
in :mod:`yoke_cli.config.universe_ui_launchd`.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any, Dict, Optional

from yoke_cli.config import universe_ui_launchd as launchd
from yoke_cli.config.universe_ui_daemon_state import (
    UiDaemonError,
    UiDaemonRecord,
    clear_record,
    log_path,
    log_tail,
    port_accepting,
    private_url,
    process_alive,
    read_record,
    stable_session_token,
    state_dir,
    write_record,
)

READY_TIMEOUT_S = 20.0
READY_POLL_INTERVAL_S = 0.2
STOP_TIMEOUT_S = 10.0
STOP_POLL_INTERVAL_S = 0.2


def status() -> Dict[str, Any]:
    """Report whether the machine's UI daemon is serving, and where.

    A record whose process is gone is stale — a reboot without the
    launchd agent, a ``kill -9`` — so it is cleared here rather than
    left to misreport the next reader.
    """
    record = read_record()
    if record is None:
        return _stopped_report()
    if not process_alive(record.pid):
        clear_record()
        return {
            **_stopped_report(),
            "cleared_stale_record_for_pid": record.pid,
        }
    return {
        "running": True,
        "pid": record.pid,
        "host": record.host,
        "port": record.port,
        "env": record.env,
        "started_at": record.started_at,
        "serving": port_accepting(record.host, record.port),
        "supervised_by_launchd": record.supervised,
        "state_dir": str(state_dir()),
        "private_url": private_url(
            record.host, record.port, stable_session_token(),
        ),
    }


def up(*, host: str, port: int, env: str) -> Dict[str, Any]:
    """Start the detached UI daemon, or report the one already serving."""
    current = status()
    if current.get("running"):
        return {**current, "started": False}

    stable_session_token()
    log = log_path()
    supervised = launchd.supported()
    if supervised:
        launchd.install_agent(host=host, port=port, env=env, log_path=log)
    else:
        _spawn_detached(host=host, port=port, env=env)

    if _await_ready(host=host, port=port) is None:
        _tear_down(supervised=supervised)
        tail = log_tail()
        raise UiDaemonError(
            f"the UI daemon did not begin serving {host}:{port} within "
            f"{READY_TIMEOUT_S:.0f}s, so nothing is left running. Its log "
            f"is {log}" + (f"; last lines:\n{tail}" if tail else "")
        )
    return {**status(), "started": True}


def down() -> Dict[str, Any]:
    """Stop the daemon and drop its supervisor. The token survives."""
    removed_agent = launchd.remove_agent()
    record = read_record()
    stopped_pid: Optional[int] = None
    if record is not None and process_alive(record.pid):
        _terminate(record.pid)
        stopped_pid = record.pid
    clear_record()
    report: Dict[str, Any] = {
        "running": False,
        "stopped": stopped_pid is not None,
        "removed_launchd_agent": removed_agent,
        "state_dir": str(state_dir()),
    }
    if stopped_pid is not None:
        report["stopped_pid"] = stopped_pid
    return report


def publish_serving_identity(*, host: str, port: int, env: str) -> None:
    """Called by the serving child once it owns the port."""
    write_record(
        pid=os.getpid(),
        host=host,
        port=port,
        env=env,
        supervised=launchd.agent_installed(),
    )


def retract_serving_identity() -> None:
    """Called by the serving child on exit, if the record is still its own."""
    record = read_record()
    if record is not None and record.pid == os.getpid():
        clear_record()


def _stopped_report() -> Dict[str, Any]:
    return {
        "running": False,
        "supervised_by_launchd": launchd.agent_installed(),
        "state_dir": str(state_dir()),
    }


def _spawn_detached(*, host: str, port: int, env: str) -> None:
    command = launchd.child_command(host=host, port=port, env=env)
    try:
        with open(log_path(), "w", encoding="utf-8") as log:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log,
                start_new_session=True,
                env=launchd.child_environment(env),
            )
    except OSError as exc:
        raise UiDaemonError(
            f"the UI daemon could not be started ({exc}); the command was "
            f"{' '.join(command)}"
        ) from exc


def _await_ready(*, host: str, port: int) -> Optional[UiDaemonRecord]:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        record = read_record()
        if (
            record is not None
            and process_alive(record.pid)
            and port_accepting(host, port)
        ):
            return record
        time.sleep(READY_POLL_INTERVAL_S)
    return None


def _tear_down(*, supervised: bool) -> None:
    if supervised:
        launchd.remove_agent()
    record = read_record()
    if record is not None and process_alive(record.pid):
        _terminate(record.pid)
    clear_record()


def _terminate(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    deadline = time.monotonic() + STOP_TIMEOUT_S
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return
        time.sleep(STOP_POLL_INTERVAL_S)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


__all__ = [
    "READY_TIMEOUT_S",
    "STOP_TIMEOUT_S",
    "UiDaemonError",
    "down",
    "publish_serving_identity",
    "retract_serving_identity",
    "status",
    "up",
]

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

from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.timestamps import format_instant
from yoke_contracts import platform_process
from yoke_contracts.owner_private_path import write_owner_private

import os
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

from yoke_cli.config import universe_ui_launchd as launchd
from yoke_cli.config.universe_ui_launchd import UiLaunchdError
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
    require_available_port,
    record_path,
    stable_session_token,
    state_dir,
    write_record,
)

READY_TIMEOUT_S = 20.0
READY_POLL_INTERVAL_S = 0.2
STOP_TIMEOUT_S = 10.0


def status() -> Dict[str, Any]:
    """Report whether the machine's UI daemon is serving, and where.

    A record whose process is gone is stale — a reboot without the
    launchd agent, a ``kill -9`` — so it is cleared here rather than
    left to misreport the next reader.
    """
    record = read_record()
    if record is None:
        return _stopped_report()
    if not process_alive(record.pid, record.process_start_time):
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
        "started_at": format_instant(record.started_at),
        "serving": port_accepting(record.host, record.port),
        "supervised_by_launchd": record.supervised,
        "state_dir": str(state_dir()),
        "private_url": private_url(
            record.host,
            record.port,
            stable_session_token(),
        ),
    }


def up(*, host: str, port: int, env: str) -> Dict[str, Any]:
    """Start the detached UI daemon, or report the one already serving."""
    current = status()
    if current.get("running"):
        return {**current, "started": False}

    require_available_port(host, port)
    stable_session_token()
    log = log_path()
    supervised, note, child = _start_supervisor(host=host, port=port, env=env, log=log)

    try:
        ready = _await_ready(host=host, port=port)
    except UiDaemonError:
        _tear_down(supervised=supervised, child=child)
        raise
    if ready is None:
        _tear_down(supervised=supervised, child=child)
        tail = log_tail()
        raise UiDaemonError(
            f"the UI daemon did not begin serving {host}:{port} within "
            f"{READY_TIMEOUT_S:.0f}s, so nothing is left running. Its log "
            f"is {log}; inspect it and retry `yoke ui up --port PORT`" + (f"; last lines:\n{tail}" if tail else "")
        )
    report = {**status(), "started": True}
    if note:
        report["supervisor_note"] = note
    return report


def down() -> Dict[str, Any]:
    """Stop the daemon and drop its supervisor. The token survives."""
    removed_agent = launchd.remove_agent()
    record = read_record()
    stopped_pid: Optional[int] = None
    if record is not None and process_alive(record.pid, record.process_start_time):
        _terminate(record)
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


def restart_running() -> Dict[str, Any]:
    """Replace a running machine dashboard using its saved serving settings."""
    record = read_record()
    if record is None:
        if record_path().exists():
            raise UiDaemonError(
                "ui_restart_identity_invalid: the dashboard process record is unreadable; "
                "inspect the dashboard process and stop it before running "
                "`yoke ui down` and `yoke ui up --no-browser`, then rerun the installer."
            )
        return {"restarted": False}
    if not process_alive(record.pid, record.process_start_time):
        clear_record()
        return {"restarted": False}
    down()
    if process_alive(record.pid, record.process_start_time):
        write_record(
            pid=record.pid,
            host=record.host,
            port=record.port,
            env=record.env,
            supervised=False,
            process_start_time=record.process_start_time,
        )
        raise UiDaemonError(
            "ui_restart_stop_failed: the previous dashboard process is still alive; "
            "stop it with `yoke ui down`, then rerun the installer."
        )
    try:
        up(host=record.host, port=record.port, env=record.env)
    except (UiDaemonError, UiLaunchdError, OSError) as exc:
        raise UiDaemonError(
            f"ui_restart_start_failed: {exc}; run "
            f"`yoke --env {record.env} ui up --host {record.host} "
            f"--port {record.port} --no-browser`, then rerun the installer."
        ) from exc
    return {"restarted": True}


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


def _start_supervisor(
    *,
    host: str,
    port: int,
    env: str,
    log: Path,
) -> Tuple[bool, str, Any]:
    """Bring the serving child up, and report who is supervising it.

    The launch agent is preferred on macOS because it is what survives a
    reboot, but it is not a requirement: a session with no reachable GUI
    launchd domain — an SSH login, most commonly — still gets a view that
    outlives its terminal, and is told which supervisor it got.
    """
    if launchd.supported():
        try:
            launchd.install_agent(host=host, port=port, env=env, log_path=log)
        except UiLaunchdError as exc:
            child = _spawn_detached(host=host, port=port, env=env)
            return False, (
                f"launchd would not supervise this view ({exc}), so it is "
                "running as a detached process instead: it survives this "
                "terminal, but not a reboot. Run `yoke ui up` again from a "
                "logged-in desktop session to register the launch agent."
            ), child
        return True, "", None
    return False, "", _spawn_detached(host=host, port=port, env=env)


def _stopped_report() -> Dict[str, Any]:
    return {
        "running": False,
        "supervised_by_launchd": launchd.agent_installed(),
        "state_dir": str(state_dir()),
    }


def _spawn_detached(*, host: str, port: int, env: str):
    command = launchd.child_command(host=host, port=port, env=env)
    try:
        detached = {"creationflags": subprocess.DETACHED_PROCESS} if os.name == "nt" else {}
        write_owner_private(log_path(), "")
        with open(log_path(), "a", encoding="utf-8") as log:
            return platform_process.spawn_group(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log,
                env=launchd.child_environment(env),
                **detached,
            )
    except OSError as exc:
        raise UiDaemonError(
            f"the UI daemon could not be started ({exc}); the command was "
            f"{' '.join(command)}"
        ) from exc


def _await_ready(*, host: str, port: int) -> Optional[UiDaemonRecord]:
    announce_designed_wait(
        f"the UI daemon to accept connections on {host}:{port}",
        max_wait_seconds=READY_TIMEOUT_S,
        cadence=poll_every(READY_POLL_INTERVAL_S),
    )
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        record = read_record()
        if (
            record is not None
            and process_alive(record.pid, record.process_start_time)
            and port_accepting(host, port)
        ):
            return record
        time.sleep(READY_POLL_INTERVAL_S)
    return None


def _tear_down(*, supervised: bool, child=None) -> None:
    if supervised:
        launchd.remove_agent()
    if child is not None:
        try:
            platform_process.stop_group(child, STOP_TIMEOUT_S)
        except (OSError, TimeoutError) as exc:
            raise UiDaemonError(
                f"ui_start_cleanup_failed: could not stop starting PID {child.pid} "
                f"({exc}); inspect and stop it as its owner, then retry `yoke ui up`."
            ) from exc
    record = read_record()
    if record is not None and process_alive(record.pid, record.process_start_time):
        _terminate(record)
    clear_record()


def _terminate(record: UiDaemonRecord) -> None:
    try:
        handle = platform_process.handle_from_pid(record.pid, record.process_start_time)
        if handle is not None:
            platform_process.stop_group(handle, STOP_TIMEOUT_S)
    except (OSError, TimeoutError) as exc:
        raise UiDaemonError(
            f"ui_stop_failed: could not stop dashboard process {record.pid} "
            f"({exc}); inspect that process, stop it, then retry `yoke ui down`."
        ) from exc


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

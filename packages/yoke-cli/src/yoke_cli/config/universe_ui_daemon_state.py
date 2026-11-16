"""Machine-local custody of the UI daemon's token, record, and log.

The UI view belongs to the machine, not to one terminal, so everything
that outlives a shell lives here: the stable session token, the record
the serving process publishes about itself, and the log its stderr goes
to. :mod:`yoke_cli.config.universe_ui_daemon` owns the lifecycle that
reads and writes these; this module owns the files.

Token custody is why this is a file rather than a variable. A token
minted per run would hand the operator a different URL after every
restart, so it is minted once into a ``0600`` file under the machine
state directory and reused for the life of that directory. It never
travels on argv — ``ps`` publishes argv to every process on the machine —
never reaches the daemon record, and never reaches a log.
"""

from __future__ import annotations

from yoke_contracts.timestamps import (
    InvalidInstant,
    iso8601_now as _now_iso,
    parse_instant,
)

from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts import platform_process
from yoke_contracts.owner_private_path import (
    create_owner_private_directory, write_owner_private,
)

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import socket
import time
from typing import Optional

from yoke_cli.config import machine_config

#: Machine state directory for the UI daemon, under the machine home.
UI_STATE_DIR_NAME = "ui"
TOKEN_FILE_NAME = "session-token"
RECORD_FILE_NAME = "daemon.json"
LOG_FILE_NAME = "daemon.log"

#: ``secrets.token_urlsafe`` byte length for the machine's stable token.
SESSION_TOKEN_BYTES = 32

PORT_PROBE_TIMEOUT_S = 0.5
LOG_TAIL_LINES = 20
_RECORD_READ_ATTEMPTS = 4 if os.name == "nt" else 1


class UiDaemonError(RuntimeError):
    """The UI daemon could not be started, inspected, or stopped."""


@dataclass(frozen=True)
class UiDaemonRecord:
    """What the serving process published about itself."""

    pid: int
    host: str
    port: int
    env: str
    started_at: datetime
    supervised: bool
    process_start_time: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", parse_instant(self.started_at))


def state_dir() -> Path:
    directory = machine_config.yoke_home() / UI_STATE_DIR_NAME
    try:
        create_private_directory(directory.parent)
        return (create_owner_private_directory(directory) if os.name == "nt"
                else create_private_directory(directory))
    except OSError as exc:
        raise UiDaemonError(
            f"ui_state_unavailable: cannot prepare private dashboard state at "
            f"{directory} ({exc}); repair owner access, then retry `yoke ui up`."
        ) from exc


def token_path() -> Path:
    return state_dir() / TOKEN_FILE_NAME


def record_path() -> Path:
    return state_dir() / RECORD_FILE_NAME


def log_path() -> Path:
    return state_dir() / LOG_FILE_NAME


def stable_session_token() -> str:
    """Return this machine's UI token, minting it on first use.

    Stable by design: browser admission survives ``down`` and ``up``
    again on the same machine without printing the credential.
    """
    path = token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    except OSError as exc:
        raise UiDaemonError(
            f"the UI session token at {path} cannot be read ({exc}); "
            "delete that file to mint a new one, then run `yoke ui up`"
        ) from exc
    if existing:
        return existing
    minted = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    _write_private(path, minted)
    return minted


def _read_record_text(path: Path) -> str:
    # Windows can briefly deny opens while an atomic rename is completing.
    # Retry only this read; persistent access failures remain named refusals.
    for attempt in range(_RECORD_READ_ATTEMPTS):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            if attempt == _RECORD_READ_ATTEMPTS - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise AssertionError("record read attempts must be positive")


def read_record() -> Optional[UiDaemonRecord]:
    try:
        document = json.loads(_read_record_text(record_path()))
    except (FileNotFoundError, ValueError):
        return None
    except OSError as exc:
        raise UiDaemonError(
            f"ui_record_unreadable: cannot read {record_path()} ({exc}); "
            "repair owner access, then retry `yoke ui status`."
        ) from exc
    if not isinstance(document, dict):
        return None
    try:
        return UiDaemonRecord(
            pid=int(document.get("pid") or 0),
            host=str(document.get("host") or ""),
            port=int(document.get("port") or 0),
            env=str(document.get("env") or ""),
            started_at=document.get("started_at"),
            supervised=bool(document.get("supervised")),
            process_start_time=float(document["process_start_time"]),
        )
    except InvalidInstant:
        raise
    except KeyError as exc:
        raise UiDaemonError(
            f"ui_process_identity_missing: dashboard record {record_path()} lacks "
            f"process creation time for PID {document.get('pid')}; inspect and "
            "stop that process, remove the record, then run `yoke ui up`."
        ) from exc
    except (TypeError, ValueError):
        return None


def write_record(
    *,
    pid: int,
    host: str,
    port: int,
    env: str,
    supervised: bool,
    process_start_time: float | None = None,
) -> None:
    """Publish the serving process's own identity. Never carries the token."""
    if process_start_time is None:
        process_start_time = next(
            (info.start_time for info in platform_process.process_command_lines()
             if info.pid == pid), 0.0,
        )
    _write_private(
        record_path(),
        json.dumps(
            {
                "pid": int(pid),
                "host": host,
                "port": int(port),
                "env": env,
                "started_at": _now_iso(),
                "supervised": bool(supervised),
                "process_start_time": process_start_time,
            },
            sort_keys=True,
        ),
    )


def clear_record() -> None:
    record_path().unlink(missing_ok=True)


def process_alive(pid: int, start_time: float | None = None) -> bool:
    try:
        return platform_process.pid_alive(pid, start_time=start_time)
    except OSError as exc:
        raise UiDaemonError(
            f"ui_process_inspection_failed: cannot inspect PID {pid} ({exc}); "
            "run as its owner, then retry `yoke ui status`."
        ) from exc


def require_available_port(host: str, port: int) -> None:
    """Refuse occupied and Windows-reserved ports before spawning a daemon."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((host, port))
    except OSError as exc:
        raise UiDaemonError(
            f"ui_port_unavailable: cannot bind {host}:{port} ({exc}); "
            "the port may be occupied or reserved by Windows/Hyper-V. "
            "Choose another port with `yoke ui up --port PORT`."
        ) from exc


def port_accepting(host: str, port: int) -> bool:
    if not host or port <= 0:
        return False
    try:
        with socket.create_connection((host, port), PORT_PROBE_TIMEOUT_S):
            return True
    except OSError:
        return False


def private_url(host: str, port: int, token: str) -> str:
    """The tokened door — terminal-only output, never logged."""
    return f"http://{host}:{port}/?token={token}"


def log_tail() -> str:
    try:
        lines = log_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-LOG_TAIL_LINES:])


def _write_private(path: Path, content: str) -> None:
    try:
        write_owner_private(path, content)
    except OSError as exc:
        raise UiDaemonError(
            f"ui_private_write_failed: cannot write {path} ({exc}); "
            "repair owner access and close open file handles, then retry `yoke ui up`."
        ) from exc


__all__ = [
    "LOG_FILE_NAME",
    "LOG_TAIL_LINES",
    "RECORD_FILE_NAME",
    "SESSION_TOKEN_BYTES",
    "TOKEN_FILE_NAME",
    "UI_STATE_DIR_NAME",
    "UiDaemonError",
    "UiDaemonRecord",
    "clear_record",
    "log_path",
    "log_tail",
    "port_accepting",
    "private_url",
    "process_alive",
    "read_record",
    "record_path",
    "stable_session_token",
    "state_dir",
    "token_path",
    "write_record",
]

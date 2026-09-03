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

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
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


class UiDaemonError(RuntimeError):
    """The UI daemon could not be started, inspected, or stopped."""


@dataclass(frozen=True)
class UiDaemonRecord:
    """What the serving process published about itself."""

    pid: int
    host: str
    port: int
    env: str
    started_at: str
    supervised: bool


def state_dir() -> Path:
    directory = machine_config.yoke_home() / UI_STATE_DIR_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def token_path() -> Path:
    return state_dir() / TOKEN_FILE_NAME


def record_path() -> Path:
    return state_dir() / RECORD_FILE_NAME


def log_path() -> Path:
    return state_dir() / LOG_FILE_NAME


def stable_session_token() -> str:
    """Return this machine's UI token, minting it on first use.

    Stable by design: the tokened URL is the operator's bookmark, so it
    has to survive ``down`` and ``up`` again on the same machine.
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


def read_record() -> Optional[UiDaemonRecord]:
    try:
        document = json.loads(record_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None
    if not isinstance(document, dict):
        return None
    try:
        return UiDaemonRecord(
            pid=int(document.get("pid") or 0),
            host=str(document.get("host") or ""),
            port=int(document.get("port") or 0),
            env=str(document.get("env") or ""),
            started_at=str(document.get("started_at") or ""),
            supervised=bool(document.get("supervised")),
        )
    except (TypeError, ValueError):
        return None


def write_record(
    *,
    pid: int,
    host: str,
    port: int,
    env: str,
    supervised: bool,
) -> None:
    """Publish the serving process's own identity. Never carries the token."""
    _write_private(record_path(), json.dumps({
        "pid": int(pid),
        "host": host,
        "port": int(port),
        "env": env,
        "started_at": _now_iso(),
        "supervised": bool(supervised),
    }, sort_keys=True))


def clear_record() -> None:
    record_path().unlink(missing_ok=True)


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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


def _now_iso() -> str:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return stamp.replace("+00:00", "Z")


def _write_private(path: Path, content: str) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


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

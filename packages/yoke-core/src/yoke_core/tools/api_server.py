"""Yoke API server launcher.

Provides start/restart/stop commands for the Yoke API uvicorn process.
Invoke via ``python3 -m yoke_core.tools.api_server start|restart|stop``.

PID file location: ``<repo_root>/runtime/api/.pid``.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, List


def _resolve_repo_root() -> Path:
    """Walk up from this file to the Yoke repo root."""
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _pid_file() -> Path:
    return _resolve_repo_root() / "runtime" / "api" / ".pid"


def _log_file() -> Path:
    """Return the API-server log path.

    Resolves to ``$YOKE_API_LOG`` when set; otherwise the helper-resolved
    machine temp root's ``storage/api-server/yoke-api-server.log`` path,
    so the log inherits the scratch override (``YOKE_SCRATCH_ROOT`` /
    machine-config ``temp_root``) like every other Yoke-owned scratch write.
    """
    override = os.environ.get("YOKE_API_LOG", "").strip()
    if override:
        return Path(override)
    from yoke_core.domain.project_scratch_dir import storage_path

    return storage_path("api-server", "yoke-api-server.log")


def _read_pid(pid_file: Path) -> Optional[int]:
    if not pid_file.is_file():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_existing(pid_file: Path) -> None:
    """Kill any process referenced by the PID file, waiting up to 5s for exit."""
    old_pid = _read_pid(pid_file)
    if old_pid is None:
        return

    if _is_alive(old_pid):
        print(f"Stopping Yoke API (PID {old_pid}) ...")
        try:
            os.kill(old_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        waited = 0
        while _is_alive(old_pid) and waited < 5:
            time.sleep(1)
            waited += 1

        if _is_alive(old_pid):
            print(f"Force killing PID {old_pid} ...")
            try:
                os.kill(old_pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    try:
        pid_file.unlink()
    except FileNotFoundError:
        pass


def cmd_start() -> int:
    """Start the Yoke API uvicorn server."""
    repo_root = _resolve_repo_root()
    pid_file = _pid_file()
    port = os.environ.get("YOKE_API_PORT", "8765")
    host = os.environ.get("YOKE_API_HOST", "127.0.0.1")

    old_pid = _read_pid(pid_file)
    if old_pid and _is_alive(old_pid):
        print(
            f"Yoke API already running (PID {old_pid}). "
            f"Use `api_server restart` to restart.",
        )
        return 1
    if old_pid and not _is_alive(old_pid):
        try:
            pid_file.unlink()
        except FileNotFoundError:
            pass

    log_file = _log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"Starting Yoke API on {host}:{port} ...")
    # Deployment pipeline stages capture and then close their stdio pipes.
    # Detach uvicorn from those pipes so the API keeps running for the
    # following health-check stage and for local operators after deploy.
    with log_file.open("ab") as log_handle:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "yoke_core.api.main:app",
                "--host",
                host,
                "--port",
                port,
            ],
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
    print(
        f"Yoke API started (PID {proc.pid}). "
        f"PID file: {pid_file}. Log: {log_file}"
    )
    return 0


def cmd_restart() -> int:
    """Restart the Yoke API server (stop + start)."""
    pid_file = _pid_file()
    _kill_existing(pid_file)
    return cmd_start()


def cmd_stop() -> int:
    """Stop the Yoke API server if it is running."""
    pid_file = _pid_file()
    old_pid = _read_pid(pid_file)
    if old_pid is None or not _is_alive(old_pid):
        print("Yoke API is not running.")
        try:
            pid_file.unlink()
        except FileNotFoundError:
            pass
        return 0
    _kill_existing(pid_file)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yoke-api-server",
        description="Start, restart, or stop the Yoke API uvicorn server.",
    )
    parser.add_argument(
        "command",
        choices=("start", "restart", "stop"),
        help="Lifecycle action to perform.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "start":
        sys.exit(cmd_start())
    elif args.command == "restart":
        sys.exit(cmd_restart())
    elif args.command == "stop":
        sys.exit(cmd_stop())
    sys.exit(1)


if __name__ == "__main__":
    main()

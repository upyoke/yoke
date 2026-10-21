"""Stop the machine's evaluator, then warm and prove the installed evaluator."""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import time

from yoke_cli import hook_resident_client as client
from yoke_contracts import platform_file_lock
from yoke_contracts.process_ancestry import process_command_name, process_start_time
from yoke_contracts.designed_wait import announce_designed_wait, poll_every

LIFECYCLE_USAGE = "yoke hook resident {restart|stop}"
_STOP_SECONDS = 20.0
# Covers a cold evaluator import on a small machine; setup and installs wait here.
_START_SECONDS = 60.0
_RETRY_SECONDS = 0.05


class ResidentLifecycleError(RuntimeError):
    """A lifecycle operation failed with its reason and recovery."""


def _failure(
    code: str, detail: str, paths: client.ResidentPaths
) -> ResidentLifecycleError:
    return ResidentLifecycleError(
        f"{code}: {detail}; inspect {paths.log}, then run "
        "yoke hook resident restart. For uninstall, close hook callers and retry uninstall."
    )


def _resident_processes(paths: client.ResidentPaths) -> list[tuple[int, str]]:
    # Match both the Python module and exact machine socket, never a substring
    # in an unrelated command. ps restricts discovery to this OS user's processes.
    try:
        result = subprocess.run(
            ["ps", "-ww", "-u", str(os.getuid()), "-o", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode:
            raise OSError("process listing failed")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _failure("YOKE_HOOK_RESIDENT_STOP_FAILED", str(exc), paths) from None
    residents = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        pattern = (
            r".+? -m yoke_harness\.hook_resident --socket "
            + re.escape(str(paths.socket))
            + r" --lock-fd \d+"
        )
        if not re.fullmatch(pattern, fields[1]):
            continue
        pid = int(fields[0])
        if not re.fullmatch(
            r"python(?:\d+(?:\.\d+)*)?", process_command_name(pid) or ""
        ):
            continue
        started = process_start_time(pid)
        if started:
            residents.append((pid, started))
    return residents


def stop_resident(
    paths: client.ResidentPaths | None = None, *, require_lock_release: bool = True
) -> None:
    """Signal only proven residents and wait for process exit and lock release.

    A restart passes ``require_lock_release=False``: once the old residents
    exit, a resident a live hook launched meanwhile already runs the
    installed build, and its lock must not fail the restart.
    """
    if not client.resident_transport_available():
        return
    paths = paths or client.resident_paths()
    residents = _resident_processes(paths)
    for pid, started in residents:
        if process_start_time(pid) != started:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise _failure("YOKE_HOOK_RESIDENT_STOP_FAILED", str(exc), paths) from None
    deadline = time.monotonic() + _STOP_SECONDS
    if residents:
        announce_designed_wait(
            "hook evaluator exit and lock release",
            max_wait_seconds=_STOP_SECONDS,
            cadence=poll_every(_RETRY_SECONDS),
        )
    while time.monotonic() < deadline:
        alive = any(process_start_time(pid) == started for pid, started in residents)
        if not alive and not require_lock_release:
            return
        if not alive:
            lock_fd = client._open_start_lock(paths.lock)
            if lock_fd is not None:
                os.close(lock_fd)
                return
        time.sleep(_RETRY_SECONDS)
    raise _failure(
        "YOKE_HOOK_RESIDENT_STOP_TIMEOUT",
        "the evaluator did not exit or another hook caller holds its lock",
        paths,
    )


def restart_resident() -> None:
    """Restart even a same-version install; a dry evaluation proves readiness."""
    paths = client.resident_paths()
    if not client.resident_transport_available():
        raise _failure(
            "YOKE_HOOK_RESIDENT_UNSUPPORTED",
            "Unix-domain socket transport is unavailable on this platform",
            paths,
        )
    lock_fd = os.open(paths.state_dir / "lifecycle.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            platform_file_lock.acquire_exclusive_nonblocking(lock_fd)
        except BlockingIOError:
            raise _failure(
                "YOKE_HOOK_RESIDENT_LIFECYCLE_BUSY",
                "another installer is changing the evaluator",
                paths,
            ) from None
        stop_resident(paths, require_lock_release=False)
        request = client._request("PreToolUse", "{}", True, "")
        client._start_resident(paths, request.environment)
        deadline = time.monotonic() + _START_SECONDS
        announce_designed_wait(
            "installed hook evaluator dry evaluation",
            max_wait_seconds=_START_SECONDS,
            cadence=poll_every(_RETRY_SECONDS),
        )
        last_error = "the evaluator has not answered"
        while time.monotonic() < deadline:
            try:
                response = client._round_trip(paths, request, deadline)
                if response.get("status") == "restart":
                    last_error = client._restart_detail(response)
                else:
                    result = client._validated_result(response, paths)
                    if result.exit_code:
                        raise _failure(
                            "YOKE_HOOK_RESIDENT_HEALTH_FAILED",
                            f"dry evaluation returned exit {result.exit_code}",
                            paths,
                        )
                    return
            except (OSError, client.HookEvaluatorProtocolError) as exc:
                last_error = type(exc).__name__
            except client.ResidentUnavailable as exc:
                raise _failure(exc.code, exc.detail, paths) from None
            time.sleep(_RETRY_SECONDS)
        raise _failure("YOKE_HOOK_RESIDENT_START_TIMEOUT", last_error, paths)
    finally:
        os.close(lock_fd)


def resident_lifecycle(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke hook resident")
    parser.add_argument("action", choices=("restart", "stop"))
    action = parser.parse_args(args).action
    try:
        if action == "restart":
            restart_resident()
        else:
            stop_resident()
    except ResidentLifecycleError as exc:
        print(str(exc))
        return 1
    except (client.ResidentUnavailable, OSError) as exc:
        print(
            f"YOKE_HOOK_RESIDENT_LIFECYCLE_FAILED: {exc}; ensure the machine cache "
            "is writable, then run yoke hook resident restart and retry the installer."
        )
        return 1
    print("Hook evaluator: ready" if action == "restart" else "Hook evaluator: stopped")
    return 0

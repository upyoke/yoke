"""Stop the machine's evaluator, then warm and prove the installed evaluator."""

from __future__ import annotations

import argparse
import os
import re
import time

from yoke_cli import hook_resident_client as client
from yoke_cli import hook_resident_start as startup
from yoke_contracts import platform_file_lock
from yoke_contracts.designed_wait import announce_designed_wait, poll_every

LIFECYCLE_USAGE = "yoke hook resident {restart|stop}"
# SIGTERM grace, then SIGKILL for residents proven by their start time.
_STOP_SECONDS = 10.0
_KILL_SECONDS = 5.0
# Covers a cold evaluator import on a small machine; setup and installs wait here.
_START_SECONDS = 60.0
_RETRY_SECONDS = 0.05


class ResidentLifecycleError(RuntimeError):
    """A lifecycle operation failed with its reason and recovery."""


def _failure(
    code: str, detail: str, paths: client.ResidentPaths, recovery: str = ""
) -> ResidentLifecycleError:
    return ResidentLifecycleError(
        f"{code}: {detail}; "
        + (
            recovery
            or f"inspect {paths.log}, then run yoke hook resident restart. "
            "For uninstall, close hook callers and retry uninstall."
        )
    )


def _resident_processes(paths: client.ResidentPaths) -> list[tuple[int, float]]:
    """Match exact argv, retaining PID birth identity for retirement."""
    from yoke_contracts import platform_process

    try:
        processes = platform_process.process_command_lines()
    except OSError as exc:
        raise _failure("YOKE_HOOK_RESIDENT_STOP_FAILED", str(exc), paths) from None
    residents = []
    for process in processes:
        argv = process.cmdline
        if len(argv) != 7 or argv[1:4] != (
            "-m",
            "yoke_harness.hook_resident",
            "--socket",
        ):
            continue
        if argv[4] != str(paths.socket) or argv[5] not in ("--lock-fd", "--lock-path"):
            continue
        # Framework builds on macOS name the executable "Python".
        executable = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if not re.fullmatch(r"pythonw?(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable):
            continue
        residents.append((process.pid, process.start_time))
    return residents


def stop_resident(
    paths: client.ResidentPaths | None = None, *, require_lock_release: bool = True
) -> None:
    """Stop proven residents, escalating to SIGKILL, and name what remains.

    A restart passes ``require_lock_release=False``: once the old residents
    exit, a resident a live hook launched meanwhile already runs the
    installed build, and its lock must not fail the restart.
    """
    from yoke_contracts import platform_process

    if not client.resident_transport_available():
        return
    paths = paths or client.resident_paths()
    residents = _resident_processes(paths)
    if residents:
        announce_designed_wait(
            "hook evaluator exit and lock release",
            max_wait_seconds=len(residents) * _STOP_SECONDS + _KILL_SECONDS,
            cadence=poll_every(_RETRY_SECONDS),
        )
    for pid, started in residents:
        handle = platform_process.handle_from_pid(pid, started)
        if handle is None:
            continue
        try:
            platform_process.stop_group(handle, timeout=_STOP_SECONDS)
        except OSError as exc:
            raise _failure("YOKE_HOOK_RESIDENT_STOP_FAILED", str(exc), paths) from None
    alive = [
        pid for pid, started in residents if platform_process.pid_alive(pid, started)
    ]
    if alive:
        raise _failure(
            "YOKE_HOOK_RESIDENT_STOP_TIMEOUT",
            f"evaluator process {', '.join(map(str, alive))} is still running",
            paths,
            "close hook callers, restart this machine, then run yoke hook resident restart",
        )
    if not require_lock_release:
        return
    deadline = time.monotonic() + _KILL_SECONDS
    while time.monotonic() < deadline:
        lock_fd = startup._open_start_lock(paths.lock)
        if lock_fd is not None:
            os.close(lock_fd)
            return
        time.sleep(_RETRY_SECONDS)
    raise _failure(
        "YOKE_HOOK_RESIDENT_LOCK_HELD",
        f"every evaluator exited, but another hook caller holds {paths.lock}",
        paths,
        "close the harness sessions on this machine so no hook starts a new "
        "evaluator, then retry",
    )


def restart_resident() -> None:
    """Restart even a same-version install; a dry evaluation proves readiness."""
    paths = client.resident_paths()
    refusal = client.resident_transport_refusal(paths)
    if refusal is not None:
        raise _failure(*refusal, paths)
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
    parser.add_argument(
        "action",
        choices=("restart", "stop"),
        help="Restart or stop the resident hook process.",
    )
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

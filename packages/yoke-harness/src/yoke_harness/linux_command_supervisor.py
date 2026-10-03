"""Standalone Linux command custody, embedded over SSH before Yoke is installed.

The detached supervisor owns descendants (including new process sessions),
survives loss of SSH, and publishes a receipt only after verified settlement.
"""

import ctypes
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


TICK = 0.05
TERM_GRACE = 0.5
KILL_GRACE = 1.0
RECEIPT_MARKER = "YOKE_COMMAND_RECEIPT:"
HEARTBEAT = "YOKE_COMMAND_HEARTBEAT\n"
SETTLEMENT_ALLOWANCE = TERM_GRACE + KILL_GRACE + 3


def _processes():
    result = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            result[int(entry.name)] = (int(fields[1]), fields[19], fields[0])
        except (OSError, ValueError, IndexError):
            continue
    return result


def _remember(owned):
    processes = _processes()
    parents = {os.getpid()}
    changed = True
    while changed:
        changed = False
        for pid, (parent, birth, _state) in processes.items():
            if parent in parents and pid not in parents:
                parents.add(pid)
                owned[pid] = birth
                changed = True
    return processes


def _alive(owned, processes):
    return {
        pid
        for pid, birth in owned.items()
        if pid in processes and processes[pid][1] == birth and processes[pid][2] != "Z"
    }


def _reap():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if not pid:
            return


def _terminate(owned):
    # Retain identities across TERM: a dying parent cannot hide its children.
    for signum, grace in ((signal.SIGTERM, TERM_GRACE), (signal.SIGKILL, KILL_GRACE)):
        deadline = time.monotonic() + grace
        while True:
            alive = _alive(owned, _remember(owned))
            for pid in alive:
                try:
                    os.kill(pid, signum)
                except (ProcessLookupError, PermissionError):
                    pass
            _reap()
            if not alive or time.monotonic() >= deadline:
                break
            time.sleep(TICK)
    return sorted(_alive(owned, _remember(owned)))


def _write_receipt(directory, receipt):
    temporary = directory / "receipt.tmp"
    temporary.write_text(json.dumps(receipt))
    temporary.replace(directory / "receipt.json")


def _supervise(directory, connection, argv, environment, timeout):
    os.setsid()
    # Reparent orphaned grandchildren to this command owner, even after setsid.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise OSError("command subreaper unavailable")
    with open(os.devnull, "rb") as null:
        for descriptor in (0, 1, 2):
            os.dup2(null.fileno(), descriptor)
    owned = {}
    reason = "completed"
    deadline = time.monotonic() + timeout
    with (
        (directory / "stdout").open("wb") as out,
        (directory / "stderr").open("wb") as err,
    ):
        process = subprocess.Popen(
            argv,
            env={**os.environ, **environment},
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
        while True:
            _remember(owned)
            code = process.poll()
            if code is not None:
                break
            if time.monotonic() >= deadline:
                reason, code = "deadline", 124
                break
            ready, _, _ = select.select([connection], [], [], TICK)
            if ready and not os.read(connection, 1):
                reason, code = "ssh_disconnected", 124
                break
        unsettled = _terminate(owned)
        _write_receipt(
            directory,
            {
                "command_id": directory.name,
                "reason": reason,
                "returncode": code,
                "termination_verified": not unsettled,
                "unsettled_pids": unsettled,
            },
        )


def run_supervised(directory_name, argv, environment, timeout):
    """SSH guardian streams captures; pipe EOF tells the independent owner to stop."""
    os.umask(0o077)
    directory = Path(directory_name)
    directory.mkdir(mode=0o700)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(write_fd)
        try:
            _supervise(directory, read_fd, argv, environment, timeout)
        except BaseException as exc:
            _write_receipt(
                directory,
                {
                    "command_id": directory.name,
                    "termination_verified": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        finally:
            os._exit(0)
    os.close(read_fd)
    positions = {"stdout": 0, "stderr": 0}
    last_heartbeat = 0.0
    try:
        while True:
            for name, stream in (
                ("stdout", sys.stdout.buffer),
                ("stderr", sys.stderr.buffer),
            ):
                path = directory / name
                if path.exists():
                    with path.open("rb") as capture:
                        capture.seek(positions[name])
                        chunk = capture.read(65536)
                    positions[name] += len(chunk)
                    stream.write(chunk)
                    stream.flush()
            receipt_path = directory / "receipt.json"
            if receipt_path.exists():
                # Drain remaining bytes before publishing final evidence.
                if any(
                    (directory / name).exists()
                    and (directory / name).stat().st_size > position
                    for name, position in positions.items()
                ):
                    continue
                receipt = receipt_path.read_text()
                sys.stderr.write("\n" + RECEIPT_MARKER + receipt + "\n")
                sys.stderr.flush()
                return
            if time.monotonic() - last_heartbeat >= 0.2:
                sys.stderr.write(HEARTBEAT)
                sys.stderr.flush()
                last_heartbeat = time.monotonic()
            time.sleep(TICK)
    except (BrokenPipeError, ConnectionError):
        pass
    finally:
        os.close(write_fd)


def read_receipt(directory_name, wait_seconds):
    directory = Path(directory_name)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise RuntimeError("command custody directory owner invalid")
    deadline = time.monotonic() + wait_seconds
    while not (directory / "receipt.json").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("command custody unsettled")
        time.sleep(TICK)
    return json.loads((directory / "receipt.json").read_text())


def remove_settled(directory_name):
    directory = Path(directory_name)
    receipt = read_receipt(directory_name, 0)
    if receipt.get("termination_verified") is not True:
        raise RuntimeError("command custody unsettled")
    for name in ("stdout", "stderr", "receipt.json"):
        (directory / name).unlink(missing_ok=True)
    directory.rmdir()


def read_result(directory_name, wait_seconds):
    receipt = read_receipt(directory_name, wait_seconds)
    directory = Path(directory_name)
    return {
        "receipt": receipt,
        **{
            name: (directory / name).read_text(errors="backslashreplace")
            for name in ("stdout", "stderr")
            if (directory / name).exists()
        },
    }

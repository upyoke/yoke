"""Own the resident startup lock and installed-revision restart."""

import argparse
import os
import sys
import time
from pathlib import Path

from yoke_contracts.hook_resident_transport import uses_named_pipe
from yoke_contracts.machine_config.directories import create_private_directory


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yoke resident hook evaluator")
    parser.add_argument("--socket", required=True)
    lock = parser.add_mutually_exclusive_group(required=True)
    lock.add_argument("--lock-fd", type=int)
    lock.add_argument("--lock-path")
    return parser.parse_args()


def main(serve) -> int:
    args = _parse_args()
    socket_path = Path(args.socket)
    if args.lock_path:
        from yoke_cli.hook_resident_start import _open_start_lock

        args.lock_fd = _open_start_lock(Path(args.lock_path))
        deadline = time.monotonic() + 1.0
        while args.lock_fd is None and time.monotonic() < deadline:
            time.sleep(0.025)
            args.lock_fd = _open_start_lock(Path(args.lock_path))
        if args.lock_fd is None:
            return 0  # Another caller won startup; it owns the listener.
    try:
        os.fstat(args.lock_fd)
    except OSError:
        from yoke_harness.hook_observation_delivery import lock_invalid_error

        sys.stderr.write(lock_invalid_error())
        return 2
    os.set_inheritable(args.lock_fd, True)
    if not uses_named_pipe():
        create_private_directory(socket_path.parent)
    if not serve(socket_path, args.lock_fd):
        os.close(args.lock_fd)
        return 0
    if uses_named_pipe():
        os.close(args.lock_fd)
        return 0  # Waiting callers start the newly installed Python.
    from yoke_cli.config.cli_release_runtime import exec_current_python

    return exec_current_python(
        [
            "-m",
            "yoke_harness.hook_resident",
            "--socket",
            str(socket_path),
            "--lock-fd",
            str(args.lock_fd),
        ],
    )

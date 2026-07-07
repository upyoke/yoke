"""Portable timeout wrapper compatibility command."""

from __future__ import annotations

import subprocess
import sys
from typing import Iterable, Optional, Sequence, TextIO


def run_command(argv: Sequence[str], *, out: TextIO, err: TextIO) -> int:
    if len(argv) < 2:
        err.write("Usage: sh timeout-portable.sh <seconds> <command> [args...]\n")
        return 125

    timeout_text = argv[0]
    if not timeout_text.isdigit():
        err.write(
            f"timeout-portable.sh: timeout must be a positive integer, got '{timeout_text}'\n"
        )
        return 125

    timeout = int(timeout_text)
    if timeout == 0:
        err.write("timeout-portable.sh: timeout must be greater than 0\n")
        return 125

    cmd = list(argv[1:])
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            out.write(exc.stdout)
        if exc.stderr:
            err.write(exc.stderr)
        return 124

    if result.stdout:
        out.write(result.stdout)
    if result.stderr:
        err.write(result.stderr)
    return result.returncode


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    return run_command(args, out=sys.stdout, err=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

"""Wait on one detached native resume and leave its exit status on disk.

The relay that starts a resume cannot wait for it: the turn outlives the poll,
and the poll process is gone long before the native finishes. So the relay
starts this instead, as the leader of the resume's own process group, and it
holds the one file handle nobody else can — the child's exit status.

It writes that status beside the capture the native is streaming into, which
is where the next relay poll looks when it settles the attempt.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import subprocess
import sys
import time
from typing import Sequence

from yoke_core.domain import json_helper


OUTCOME_SUFFIX = ".outcome"


def resume_outcome_path(capture_path: Path) -> Path:
    """Return where the supervisor beside ``capture_path`` records its exit."""
    return capture_path.with_suffix(OUTCOME_SUFFIX)


def write_resume_outcome(
    path: Path,
    *,
    exit_code: int | None,
    now: float | None = None,
) -> bool:
    """Record one finished resume's exit status where the relay will find it."""
    payload = {
        "exit_code": None if exit_code is None else int(exit_code),
        "ended_at": int(time.time() if now is None else now),
    }
    try:
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json_helper.dumps_compact(payload), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError):
        return False
    return True


def read_resume_outcome(path: Path | None) -> tuple[bool, int | None]:
    """Return whether an outcome was recorded, and the exit status it names."""
    if path is None:
        return False, None
    try:
        payload = json_helper.loads_text(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False, None
    if not isinstance(payload, dict):
        return False, None
    code = payload.get("exit_code")
    if isinstance(code, bool) or not isinstance(code, int):
        return True, None
    return True, code


def main(argv: Sequence[str] | None = None) -> int:
    """Run one native resume to completion and record how it ended."""
    parser = argparse.ArgumentParser(prog="yoke-native-resume-watch")
    parser.add_argument("--outcome", required=True)
    parser.add_argument("native", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    native = [str(value) for value in parsed.native]
    if native and native[0] == "--":
        native = native[1:]
    outcome = Path(str(parsed.outcome))
    if not native:
        write_resume_outcome(outcome, exit_code=None)
        return 2
    try:
        # The capture is already this process's stdout and stderr, so the
        # native inherits it and its whole turn lands in one file.
        process = subprocess.Popen(native, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"native resume did not start: {exc}", file=sys.stderr)
        write_resume_outcome(outcome, exit_code=None)
        return 1
    exit_code = process.wait()
    write_resume_outcome(outcome, exit_code=exit_code)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())


__all__ = [
    "OUTCOME_SUFFIX",
    "main",
    "read_resume_outcome",
    "resume_outcome_path",
    "write_resume_outcome",
]

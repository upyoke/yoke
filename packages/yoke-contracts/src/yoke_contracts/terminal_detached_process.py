"""Run noninteractive helper processes outside the invoking terminal.

A child that inherits the terminal can read it or, like an interactive
`bash -i` probe, make its own process group the terminal's foreground job.
Setup's wizard then loses ownership and stops. These children read /dev/null
(or the pipe a caller supplies) and lead a new session with no controlling
terminal, so neither can happen. Windows ignores the session flag; its
console has no POSIX job control.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from yoke_contracts.platform_process import spawn_group, stop_group


def _detached(kwargs: dict) -> dict:
    if "input" not in kwargs:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    return {**kwargs, "start_new_session": True}


def run(argv, **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` with no terminal stdin and no controlling terminal."""
    return subprocess.run(argv, **_detached(kwargs))


def popen(argv, **kwargs) -> subprocess.Popen:
    """`subprocess.Popen` with no terminal stdin and no controlling terminal."""
    return subprocess.Popen(argv, **_detached(kwargs))


def run_group(
    argv: str | Sequence[str],
    *,
    timeout: float | None = None,
    capture_output: bool = False,
    grace_seconds: float = 5.0,
    check: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run a noninteractive helper with process-tree custody on timeout."""
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    if capture_output:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)

    group = spawn_group(argv, **kwargs)
    proc = group.process
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            stop_group(group, timeout=grace_seconds)
            exc.stdout, exc.stderr = proc.communicate(timeout=grace_seconds)
        except (OSError, subprocess.SubprocessError) as cleanup_error:
            exc.add_note(f"process group cleanup failed: {cleanup_error}")
        raise
    except BaseException:
        stop_group(group, timeout=grace_seconds)
        raise
    result = subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result

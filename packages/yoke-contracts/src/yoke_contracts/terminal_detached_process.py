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

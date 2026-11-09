"""Recognize relay-owned commands and explain their in-turn wait contract."""
from __future__ import annotations
import os
from typing import Mapping
from yoke_contracts.session_control.launch_context import LAUNCH_CONTEXT_ENV
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV

_HEADLESS_MARKER_ENV = (LAUNCH_CONTEXT_ENV, RESUME_ATTEMPT_ENV)



HEADLESS_CONTINUATION_DIRECTIVE = (
    "this caller is a headless command whose turn is its whole life. If the "
    "harness moves this call to a background task or hands back a "
    "continuation handle, the command is still running: continue that same "
    "call through the harness continuation surface until it exits. Reading "
    "the background task's output continues the call; it does not extend "
    "the harness's background time limit. Read the harness manifest's "
    "cli.launch_environment and long-command rules before starting the wait. "
    "A background-time-limit notice means incomplete work. Never start a "
    "second invocation beside a live one."
)



def headless_marker_name(environ: Mapping[str, str] | None = None) -> str:
    """Name the relay marker identifying this caller as headless, if any.

    A worker started by a relay carries its launch context; the same worker
    on a turn the relay resumed carries its resume-attempt id instead. Both
    are the relay saying it owns this process, so both answer here, and the
    name comes back so a wait-mode reason can say which one was read.
    """
    source = os.environ if environ is None else environ
    for name in _HEADLESS_MARKER_ENV:
        if str(source.get(name) or "").strip():
            return name
    return ""



def caller_is_headless_command(environ: Mapping[str, str] | None = None) -> bool:
    """Whether this process is a relay-launched worker that cannot be prompted.

    One reading of the relay's markers serves both callers: the wait-mode
    selector, which keeps such a caller in-turn, and the watcher runner,
    which tells it what a handed-back call means.
    """
    return bool(headless_marker_name(environ))


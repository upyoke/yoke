"""Shared output and child-environment helpers for command watchers."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Sequence, TextIO

from yoke_core.tools._watch_wait_mode import (
    HEADLESS_CONTINUATION_DIRECTIVE,
    caller_is_headless_command,
)


def unbuffered_child_environment(env: dict[str, str] | None) -> dict[str, str]:
    """Return an isolated child environment with immediate Python output."""
    source = os.environ if env is None else env
    return {**source, "PYTHONUNBUFFERED": "1"}


def emit_immediate(line: str, *, progress_f: TextIO, out: TextIO) -> None:
    """Write a single line straight to progress capture and stdout."""
    progress_f.write(line)
    progress_f.flush()
    out.write(line)
    out.flush()


def emit_watcher_header(
    *,
    kind: str,
    raw_capture: Path,
    progress_capture: Path,
    argv: Sequence[str],
    progress_f: TextIO,
    out: TextIO,
    outcome_only: bool,
    header_metadata: str | None,
) -> None:
    """Write standard watcher startup metadata when progress is visible."""
    if outcome_only:
        return
    emit_immediate(
        f"# watch_{kind} raw={raw_capture} progress={progress_capture} "
        f"argv={shlex.join(argv)}\n",
        progress_f=progress_f,
        out=out,
    )
    if caller_is_headless_command():
        emit_immediate(
            f"# watch_{kind} headless_continuation: "
            f"{HEADLESS_CONTINUATION_DIRECTIVE}\n",
            progress_f=progress_f,
            out=out,
        )
    if header_metadata:
        emit_immediate(
            f"{header_metadata.rstrip()}\n", progress_f=progress_f, out=out
        )


__all__ = ["emit_immediate", "emit_watcher_header", "unbuffered_child_environment"]

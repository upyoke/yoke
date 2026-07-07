"""Git-style terminal pagination for CLI output.

Pages output through a pager (``less`` by default) only when the target
stream is an interactive terminal, mirroring git's pager rules so
``yoke`` commands behave like the tools operators already know:

* **TTY-gated.** Piped or redirected output — and every non-interactive
  agent/automation call (the Bash tool is never a TTY) — writes straight
  through, never paged.
* **Pager resolution precedence:** ``YOKE_PAGER`` -> ``PAGER`` -> the
  ``less`` default. An empty ``YOKE_PAGER``/``PAGER`` or a ``cat`` pager
  disables paging (git's semantics).
* **``LESS`` defaults to ``FRX``** when unset — git's exact default:
  ``F`` quits when the output fits one screen (so short output never
  opens a pager), ``R`` passes raw control chars, ``X`` skips the
  alternate-screen clear so the output stays visible after quit.
* **Robust fallback.** A missing pager binary or a broken pager pipe
  (the user quit ``less`` early) falls back to / exits as a plain write.

The pager command is split with :func:`shlex.split`, so simple argument
forms (``less``, ``less -R``, ``/usr/bin/less -FRX``) work; a shell
pipeline in ``PAGER`` is not supported by design (no shell spawning).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from typing import List, Optional, TextIO

# Git's default pager and the LESS flags it exports when LESS is unset.
DEFAULT_PAGER = "less"
DEFAULT_LESS_FLAGS = "FRX"
# git also points the `lv` pager at raw mode; harmless when lv is unused.
DEFAULT_LV_FLAGS = "-c"
# Pager values that mean "do not page" (git treats `cat`/empty this way).
_DISABLED_PAGER_VALUES = frozenset({"", "cat"})


def resolve_pager() -> Optional[str]:
    """Return the pager command string, or ``None`` when paging is disabled.

    Precedence mirrors git: ``YOKE_PAGER`` -> ``PAGER`` -> ``less``. An
    explicitly empty ``YOKE_PAGER``/``PAGER`` or a ``cat`` pager
    disables paging.
    """
    for name in ("YOKE_PAGER", "PAGER"):
        if name in os.environ:
            value = os.environ[name].strip()
            if value in _DISABLED_PAGER_VALUES:
                return None
            return value
    return DEFAULT_PAGER


def should_paginate(stream: TextIO, *, enabled: bool = True) -> bool:
    """True when output to ``stream`` should be paged.

    Paging requires the caller to opt in (``enabled``), an interactive
    TTY stream, and a non-disabled pager.
    """
    if not enabled:
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        if not isatty():
            return False
    except ValueError:
        # Stream closed underneath us.
        return False
    return resolve_pager() is not None


def page_or_write(
    content: str,
    *,
    stream: Optional[TextIO] = None,
    enabled: bool = True,
) -> None:
    """Write ``content`` to ``stream``, paging through a pager when apt.

    ``stream`` defaults to the live :data:`sys.stdout` (resolved at call
    time so ``redirect_stdout`` still works). Falls back to a direct
    write when paging is disabled, the stream is not a TTY, the pager
    binary is missing, or the pager pipe breaks.
    """
    if stream is None:
        stream = sys.stdout
    if not should_paginate(stream, enabled=enabled):
        _write_direct(content, stream)
        return
    pager = resolve_pager()
    if pager is None or not _page_through(content, pager):
        _write_direct(content, stream)


def _write_direct(content: str, stream: TextIO) -> None:
    try:
        stream.write(content)
        stream.flush()
    except BrokenPipeError:
        # Downstream consumer (e.g. `| head`) closed early — nothing to do.
        pass


def _page_through(content: str, pager: str) -> bool:
    """Spawn ``pager`` and feed ``content`` to its stdin.

    Returns ``True`` when the pager ran (even if the user quit early so
    the input pipe broke), ``False`` when the pager binary was missing so
    the caller falls back to a direct write.
    """
    argv = _pager_argv(pager)
    if argv is None:
        return False
    env = dict(os.environ)
    env.setdefault("LESS", DEFAULT_LESS_FLAGS)
    env.setdefault("LV", DEFAULT_LV_FLAGS)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, env=env, text=True)
    except OSError:
        return False
    try:
        proc.communicate(content)
    except (BrokenPipeError, OSError):
        # Pager closed its input early (the user quit before reading all
        # output). The pager still ran; no direct-write fallback.
        pass
    return True


def _pager_argv(pager: str) -> Optional[List[str]]:
    """Split the pager command into argv, resolving the binary on PATH.

    Returns ``None`` when the command is empty or the resolved binary is
    not executable, so the caller falls back to a direct write.
    """
    parts = shlex.split(pager)
    if not parts:
        return None
    if shutil.which(parts[0]) is None:
        return None
    return parts


__all__ = [
    "DEFAULT_LESS_FLAGS",
    "DEFAULT_PAGER",
    "page_or_write",
    "resolve_pager",
    "should_paginate",
]

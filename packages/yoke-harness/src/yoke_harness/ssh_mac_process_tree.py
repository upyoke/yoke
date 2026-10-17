"""Stop a macOS process and every process under it, and prove they are gone.

A command the Terminal bridge gave up on keeps running unless something stops
it: one `yoke setup` did, writing into output files the bridge had already
deleted and holding its setup lock until its own approval wait expired. So a
timeout stops the whole tree, deepest first, and reports which processes, if
any, survived both signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# Prints PID and every descendant, deepest first, so a parent never respawns
# a child the walk already signalled.
PROCESS_TREE_FUNCTION = (
    'process_tree() { for c in $(/usr/bin/pgrep -P "$1"); do process_tree "$c"; '
    'done; echo "$1"; }'
)
TERM_WAIT_SECONDS = 5
_SURVIVED = 1


@dataclass(frozen=True)
class ProcessTreeStop:
    """What stopping one process tree proved."""

    stopped: bool
    survivors: tuple[int, ...] = ()
    detail: str = ""


def _stop_script(pid: int) -> str:
    return (
        f"{PROCESS_TREE_FUNCTION}; pids=$(process_tree {pid}); "
        'alive() { for p in $1; do /bin/kill -0 "$p" 2>/dev/null && echo "$p"; '
        "done; }; "
        "/bin/kill -TERM $pids 2>/dev/null; i=0; "
        f"while [ $i -lt {TERM_WAIT_SECONDS} ]; do "
        'left=$(alive "$pids"); [ -z "$left" ] && exit 0; '
        "/bin/sleep 1; i=$((i+1)); done; "
        "/bin/kill -KILL $left 2>/dev/null; /bin/sleep 1; "
        'left=$(alive "$left"); [ -z "$left" ] && exit 0; '
        f"echo $left; exit {_SURVIVED}"
    )


def stop_process_tree(run: Callable[..., object], pid: int) -> ProcessTreeStop:
    """TERM the tree under *pid*, KILL what remains, and report survivors."""
    result = run(_stop_script(pid), timeout=TERM_WAIT_SECONDS + 20)
    if result.returncode == 0:
        return ProcessTreeStop(True)
    words = (result.stdout or "").split()
    if result.returncode == _SURVIVED and words and all(w.isdigit() for w in words):
        return ProcessTreeStop(False, tuple(int(word) for word in words))
    detail = (result.stderr or result.stdout or "").strip()[:200]
    return ProcessTreeStop(False, detail=f"exit {result.returncode}: {detail}")


__all__ = [
    "PROCESS_TREE_FUNCTION",
    "ProcessTreeStop",
    "TERM_WAIT_SECONDS",
    "stop_process_tree",
]

"""Stop a macOS process and every process under it, and prove they are gone.

A command the Terminal bridge gave up on keeps running unless something stops
it: one `yoke setup` did, writing into output files the bridge had already
deleted and holding its setup lock until its own approval wait expired. So a
timeout stops the whole tree, deepest first, plus every process group a tree
member leads, which reaches descendants already re-parented away from the
tree. It reports which processes, if any, survived both signals. A process is
alive while ``ps`` still lists it (zombies excepted); ``kill -0`` would call a
process this user may not signal dead, and a ``ps`` that fails counts every
process as alive. The script runs under ``/bin/sh`` whatever the remote login
shell is: zsh does not split an unquoted ``$var`` into words, so every kill and
liveness check would see one argument holding all the PIDs.
"""

from __future__ import annotations

from dataclasses import dataclass
import shlex
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
        "groups=$(for p in $pids; do "
        '[ "$(/bin/ps -o pgid= -p "$p" | /usr/bin/tr -d " ")" = "$p" ] && echo "$p"; '
        "done); "
        'members() { echo $pids; for g in $groups; do /usr/bin/pgrep -g "$g"; done; }; '
        "alive() { t=$(/bin/ps -A -o pid=,stat=) || { echo $1; return; }; "
        'echo "$t" | /usr/bin/awk -v want="$1" '
        '\'BEGIN { n = split(want, w, " "); for (i = 1; i <= n; i++) k[w[i]] = 1 } '
        "($1 in k) && $2 !~ /^Z/ { print $1 }'; }; "
        "stop() { /bin/kill -$1 $2 2>/dev/null; "
        'for g in $groups; do /bin/kill -$1 -- "-$g" 2>/dev/null; done; }; '
        'stop TERM "$pids"; i=0; '
        f"while [ $i -lt {TERM_WAIT_SECONDS} ]; do "
        'left=$(alive "$(members)"); [ -z "$left" ] && exit 0; '
        "/bin/sleep 1; i=$((i+1)); done; "
        'stop KILL "$left"; /bin/sleep 1; '
        'left=$(alive "$(members)"); [ -z "$left" ] && exit 0; '
        f"echo $(echo $left | /usr/bin/tr ' ' '\\n' | /usr/bin/sort -un); exit {_SURVIVED}"
    )


def stop_process_tree(run: Callable[..., object], pid: int) -> ProcessTreeStop:
    """TERM the tree under *pid*, KILL what remains, and report survivors."""
    result = run(
        shlex.join(("/bin/sh", "-c", _stop_script(pid))),
        timeout=TERM_WAIT_SECONDS + 20,
    )
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

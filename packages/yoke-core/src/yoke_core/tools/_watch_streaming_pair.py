"""Rendering of the ready-to-paste streaming command pair.

Split from the watcher runtime so each file stays within the authored-
file line limit: the runner owns running a command under the raw +
progress contract, while this module owns telling a caller how to run
one and follow it.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.uv_project import uv_project_root
from yoke_contracts.watch_cli_forms import cli_form
from yoke_core.tools.watch_tail import WRAPPER_MODULE as WATCH_TAIL_MODULE


def _anchor_directory(start: Path | None = None) -> Path:
    """Return the checkout the pasted pair must ``cd`` into.

    A subdirectory cwd embeds that sticky path in the minted line, and
    the watch adapter then binds a nested or mixed environment. Prefer
    the uv-managed project that owns the lockfile; otherwise the git
    checkout; otherwise the invocation directory.
    """
    here = (start or Path.cwd()).resolve()
    found = uv_project_root(here)
    if found is not None:
        return found
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists():
            return candidate
    return here


def _invocation(wrapper_module: str) -> str:
    """Return the command that runs *wrapper_module* from a pasted shell line.

    Prefers the ``yoke watch <kind>`` console-script form, which resolves
    an interpreter that can import ``yoke_core`` from any directory.
    Wrappers with no CLI adapter fall back to the locked module form.
    """
    return cli_form(wrapper_module) or (
        f"uv run --frozen python3 -m {wrapper_module}"
    )


def _with_connection_env(invocation: str) -> str:
    """Replay the invoking connection env on a pasted command.

    ``yoke --env NAME …`` is the console-script form; module-form
    wrappers have no global flag, so they inherit ``YOKE_ENV=NAME``.
    """
    env = os.environ.get(ENV_OVERRIDE, "").strip()
    if not env:
        return invocation
    quoted = shlex.quote(env)
    if invocation.startswith("yoke "):
        return f"yoke --env {quoted} {invocation.removeprefix('yoke ')}"
    return f"{ENV_OVERRIDE}={quoted} {invocation}"


def print_streaming_pair(
    *,
    kind: str,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str] = (),
    out: Optional[TextIO] = None,
) -> None:
    """Emit a ready-to-paste background command + progress-tail pair.

    The wrapper has already filtered, so the progress command uses
    ``watch_tail`` against the progress capture. Harnesses can map the
    first line to their background-command surface and the second line
    to their streaming/progress surface. Both command lines anchor to
    the resolved repo root and replay the invoking connection env.

    Wrappers with a ``yoke watch <kind>`` adapter emit that form: the
    console script always resolves an interpreter that can import
    ``yoke_core``, and the adapter re-binds a uv-managed project's own
    environment before running. Wrappers without an adapter keep the
    ``uv run --frozen python3 -m`` module form, which binds a checkout's
    locked dependencies where ambient ``python3`` would not.
    """
    stream = out or sys.stdout
    cmd_args = shlex.join(wrapper_args)
    option_args = shlex.join(wrapper_options)
    option_prefix = f"{option_args} " if option_args else ""
    # Helper-resolved capture paths normally land under the temp scratch
    # root and contain no spaces, but ``YOKE_SCRATCH_ROOT`` and operator-
    # supplied paths can. ``shlex.quote`` keeps the printed shell shape
    # safe to copy-paste even when a segment contains whitespace.
    raw_q = shlex.quote(str(raw_capture))
    progress_q = shlex.quote(str(progress_capture))
    cwd_q = shlex.quote(str(_anchor_directory()))
    bash_invocation = (
        f"cd {cwd_q} && {_with_connection_env(_invocation(wrapper_module))} "
        f"{option_prefix}"
        f"--raw-capture {raw_q} "
        f"--progress-capture {progress_q} "
        f"-- {cmd_args}"
    )
    stream.write(f"# watch_{kind}: ready-to-paste streaming pair\n")
    stream.write("\n")
    stream.write(
        "# Background command — wrapper writes raw + progress captures\n"
    )
    stream.write(f"{bash_invocation}\n")
    stream.write("\n")
    stream.write(
        "# Progress tail — arm Monitor ONCE against this capture file.\n"
    )
    stream.write(
        "# Monitor is a subscription: matched lines arrive as wake events\n"
    )
    stream.write(
        "# for the lifetime of the bg command. Do NOT re-arm to 'continue\n"
    )
    stream.write(
        "# tail' — that is the wake-loop bug and is denied at PreToolUse.\n"
    )
    stream.write(
        "# Auto-exits when the wrapper writes its exit sentinel.\n"
    )
    stream.write(
        f"cd {cwd_q} && {_with_connection_env(_invocation(WATCH_TAIL_MODULE))} "
        f"{progress_q}\n"
    )
    stream.write("\n")
    stream.write(
        "# After completion, inspect the raw capture once for full output\n"
    )
    stream.write(f"tail -80 {raw_q}\n")
    stream.flush()

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
    the invocation cwd and run through ``uv run --frozen`` so the pasted
    command binds this checkout's locked dev dependencies and source
    packages — ambient ``python3`` may resolve an interpreter that has
    neither.
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
    # Anchor both emitted commands so execution cannot drift checkouts,
    # and let ``uv run --frozen`` resolve the anchored checkout's locked
    # environment (creating its venv if missing).
    cwd_q = shlex.quote(os.getcwd())
    locked_invocation = f"cd {cwd_q} && uv run --frozen python3 -m"
    bash_invocation = (
        f"{locked_invocation} {wrapper_module} {option_prefix}"
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
        f"{locked_invocation} yoke_core.tools.watch_tail {progress_q}\n"
    )
    stream.write("\n")
    stream.write(
        "# After completion, inspect the raw capture once for full output\n"
    )
    stream.write(f"tail -80 {raw_q}\n")
    stream.flush()

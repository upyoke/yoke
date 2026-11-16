"""Retain a resident's release and re-exec it into the current CLI."""

import os
from pathlib import Path
import sys

from yoke_cli.config import cli_release_runtime as runtime


def hold_release(*, current: bool = False) -> Path | None:
    """Lease this Python's release, or the current one, until exit and across an
    exec (an inheritable descriptor); None when this Python runs from none."""
    environment = Path(sys.executable).parent.parent.resolve()
    generation = environment.parent.parent
    released = environment.parts[-2:] == ("tools", "yoke-cli")
    if not released or generation.parent.name != "releases":
        return None
    if current:
        generation = runtime._generation(generation.parent.parent)
    lease = runtime._lease(generation)
    os.set_inheritable(lease.fileno(), True)
    runtime.HELD.append(lease)
    return generation


def exec_current_python(arguments: list[str]) -> int:
    """Replace a resident with the current release's Python, keeping its lease."""
    try:
        while runtime.HELD:  # The replaced release's lease must not survive the exec.
            runtime.HELD.pop().close()
        generation = hold_release(current=True)
        python = (
            sys.executable if generation is None else runtime.release_python(generation)
        )
        os.execv(str(python), [str(python), *arguments])
    except (OSError, RuntimeError) as exc:
        print(
            f"hook_resident_restart_failed: {exc}; {runtime.RESTART}", file=sys.stderr
        )
        return 2
    return 0

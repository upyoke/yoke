"""Restart a standing relay through its stable runtime entrypoint."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import subprocess
from typing import Callable, Sequence
from yoke_contracts.machine_config.relay_instance import WINDOWS_RELAY_RUNNER_ENV, WINDOWS_RELAY_RESTART_CODE


def exec_relay_release(
    argv: Sequence[str] | None = None,
    *,
    executable: str | Path | None = None,
    exec_call: Callable[[str, list[str]], object] = os.execv,
) -> None:
    """Replace this process; return only if the operating-system exec fails."""
    target = str(executable or sys.argv[0])
    arguments = list(sys.argv[1:] if argv is None else argv)
    if sys.platform == "win32":
        # CRT exec creates another process on Windows. Keep the scheduled
        # action's owner alive instead, and let it recycle its direct child.
        if os.environ.get(WINDOWS_RELAY_RUNNER_ENV) == "1":
            raise SystemExit(WINDOWS_RELAY_RESTART_CODE)
        root = Path(target).parent.parent
        runtime = Path((root / ".yoke-runtime-target").read_text(encoding="utf-8"))
        python = str(runtime / "Scripts" / "python.exe")
        environment = {**os.environ, WINDOWS_RELAY_RUNNER_ENV: "1"}
        while True:
            code = subprocess.call([python, "-I", str(runtime / "Scripts" / "yoke.py"), *arguments], env=environment)
            if code != WINDOWS_RELAY_RESTART_CODE:
                raise SystemExit(code)
    exec_call(target, [target, *arguments])


__all__ = ["exec_relay_release"]

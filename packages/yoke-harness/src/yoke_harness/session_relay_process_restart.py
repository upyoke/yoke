"""Restart a standing relay through its stable runtime entrypoint."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Callable, Sequence


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
        root = Path(target).parent.parent
        runtime = Path((root / ".yoke-runtime-target").read_text())
        python = str(runtime / "Scripts" / "python.exe")
        exec_call(python, [python, "-I", str(runtime / "Scripts" / "yoke.py"), *arguments])
        return
    exec_call(target, [target, *arguments])


__all__ = ["exec_relay_release"]

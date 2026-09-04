"""Replace a standing relay with the executable from a newly pinned release."""

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
    exec_call(target, [target, *arguments])


__all__ = ["exec_relay_release"]

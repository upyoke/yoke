"""Save complete oversized replies without repeating the command."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


from rich.console import Console
from rich.text import Text


_MEASUREMENT_CONSOLE = Console(width=80, color_system=None)


def wrapped_lines(text: str) -> int:
    """Measure teaching text for the authored-file validation contract."""
    return sum(
        max(
            1, len(Text.from_ansi(line).wrap(_MEASUREMENT_CONSOLE, 80, overflow="fold"))
        )
        for line in text.splitlines()
    )


def save_response(response: dict, stdout: str, stderr: str) -> Path:
    """Persist the already-redacted envelope and both complete output streams."""
    fd, filename = tempfile.mkstemp(prefix="yoke-response-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            {"response": response, "stdout": stdout, "stderr": stderr},
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
    return Path(filename)

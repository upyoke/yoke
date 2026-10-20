"""Save complete oversized replies without repeating the command."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


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

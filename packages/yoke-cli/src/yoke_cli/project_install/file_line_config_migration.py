"""Fold retired file-line exception globs into the project config file.

``.yoke/file-line-exceptions`` used to hold the authored-file exception
globs as bare lines. That policy now lives in ``.yoke/project.config`` as
repeated ``file_line_exception=`` entries alongside ``file_line_limit``,
so a project carries one on-disk config file instead of two.

Install and refresh run this so a project that still carries the retired
file moves to the new shape without losing a glob, and the retired file
stops existing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yoke_contracts.project_contract.file_line_policy import (
    FILE_LINE_EXCEPTION_KEY,
    PROJECT_CONFIG_REL,
)

RETIRED_EXCEPTIONS_REL = ".yoke/file-line-exceptions"

_MOVED_COMMENT = "# Exception globs moved out of the retired exceptions file."


def _retired_globs(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    globs: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        globs.append(line)
    return globs


def _read_existing(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def migrate_file_line_exceptions(repo_root: str | Path) -> Dict[str, Any]:
    """Move any retired exception globs into ``.yoke/project.config``.

    Returns an install-report fragment. A project with no retired file is
    already in the new shape and is left untouched.
    """
    root = Path(repo_root)
    retired = root / RETIRED_EXCEPTIONS_REL
    if not retired.is_file():
        return {"attempted": False, "status": "skipped", "moved_globs": []}

    config = root / PROJECT_CONFIG_REL
    existing = _read_existing(config)
    moved = [
        glob
        for glob in _retired_globs(retired)
        if f"{FILE_LINE_EXCEPTION_KEY}={glob}" not in existing
    ]
    if moved:
        text = existing
        if text and not text.endswith("\n"):
            text += "\n"
        entries = "".join(f"{FILE_LINE_EXCEPTION_KEY}={glob}\n" for glob in moved)
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(f"{text}\n{_MOVED_COMMENT}\n{entries}", encoding="utf-8")
    retired.unlink()
    return {
        "attempted": True,
        "status": "ok",
        "moved_globs": moved,
        "path": str(config),
    }


__all__ = ["RETIRED_EXCEPTIONS_REL", "migrate_file_line_exceptions"]

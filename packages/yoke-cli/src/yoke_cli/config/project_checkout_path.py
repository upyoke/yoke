"""Fail-closed checkout target validation before onboarding mutations."""

from __future__ import annotations

from pathlib import Path
import stat


def validation_error(value: str | Path) -> str | None:
    selected = Path(value).expanduser()
    if not str(selected):
        return "Enter a folder path."
    try:
        info = selected.lstat()
    except FileNotFoundError:
        info = None
    except OSError:
        return "That folder path can't be inspected safely — pick another path."
    if info is not None and stat.S_ISLNK(info.st_mode):
        return "That folder path is a symbolic link — pick the real project folder."
    try:
        resolved = selected.resolve(strict=False)
        home = Path.home().resolve(strict=False)
    except OSError:
        return "That folder path can't be resolved safely — pick another path."
    if resolved in {home, Path(resolved.anchor)}:
        return "That folder is not a safe project target — pick a project subfolder."
    if info is not None and not stat.S_ISDIR(info.st_mode):
        return "That path is a file, not a folder — pick a folder path."
    return None


def for_apply(
    value: str | Path, *, error_type: type[RuntimeError],
) -> Path:
    reason = validation_error(value)
    if reason is not None:
        raise error_type(reason)
    return Path(value).expanduser().resolve(strict=False)


__all__ = ["for_apply", "validation_error"]

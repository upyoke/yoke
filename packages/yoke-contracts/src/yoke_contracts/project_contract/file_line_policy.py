"""Project-local exception policy for the authored-file line-limit checker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_LIMIT = 350
FILE_LINE_LIMIT_KEY = "file_line_limit"
PROJECT_EXCEPTIONS_REL = ".yoke/file-line-exceptions"
TRACKED_GENERATED_VIEWS: tuple[str, ...] = (
    ".yoke/packs.json",
    "docs/atlas.md",
)

# Rendered strategy views are untracked local renders (gitignored via the
# seeded contract), so they never enter authored-file enforcement and no
# built-in exception glob is needed; project-local additions come from
# .yoke/file-line-exceptions.
DEFAULT_EXCEPTION_GLOBS: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileLinePolicy:
    limit: int
    exception_globs: tuple[str, ...]


def default_exception_globs() -> tuple[str, ...]:
    return DEFAULT_EXCEPTION_GLOBS


def tracked_generated_views() -> tuple[str, ...]:
    return TRACKED_GENERATED_VIEWS


def project_limit(repo_root: Path | str) -> int:
    del repo_root
    return DEFAULT_LIMIT


def project_exception_globs(repo_root: Path | str) -> tuple[str, ...]:
    path = Path(repo_root) / PROJECT_EXCEPTIONS_REL
    if not path.is_file():
        return ()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ()
    globs: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            globs.append(line)
    return tuple(globs)


def resolve_file_line_policy(repo_root: Path | str) -> FileLinePolicy:
    root = Path(repo_root)
    return FileLinePolicy(
        limit=project_limit(root),
        exception_globs=default_exception_globs() + project_exception_globs(root),
    )


__all__ = (
    "DEFAULT_EXCEPTION_GLOBS",
    "DEFAULT_LIMIT",
    "FILE_LINE_LIMIT_KEY",
    "FileLinePolicy",
    "PROJECT_EXCEPTIONS_REL",
    "TRACKED_GENERATED_VIEWS",
    "default_exception_globs",
    "project_exception_globs",
    "project_limit",
    "resolve_file_line_policy",
    "tracked_generated_views",
)

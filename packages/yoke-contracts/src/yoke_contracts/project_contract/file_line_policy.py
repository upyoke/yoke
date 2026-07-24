"""Project-owned policy for the authored-file line-limit checker.

Both the offline pre-commit checker (``yoke_harness.git_hooks``) and the
source-dev checker (``yoke_core.domain.file_line_check``) resolve their
limit and exception globs here, so the git hook and ``yoke doctor`` can
never disagree about what the limit is.

Everything lives in the checked-in ``.yoke/project.config`` contract file
that the project install seeds into every repo::

    file_line_limit=350
    file_line_exception=docs/generated-reference/**

The policy rides the repo and needs no database or network, which is what
lets the pre-commit hook enforce it offline, in a fresh clone, before any
project install has run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_LIMIT = 350
FILE_LINE_LIMIT_KEY = "file_line_limit"
FILE_LINE_EXCEPTION_KEY = "file_line_exception"
PROJECT_CONFIG_REL = ".yoke/project.config"
TRACKED_GENERATED_VIEWS: tuple[str, ...] = (
    ".yoke/packs.json",
    "docs/atlas.md",
)

# Installer-rendered agent adapters, matched on tracked path shape alone.
# `.yoke/install-manifest.json` also lists them, but it is gitignored: a
# fresh clone or CI runner has no manifest, so classifying from it made the
# same commit generated locally and authored in CI. A verdict that differs
# by environment is not a gate, so path shape is the authority here.
GENERATED_PATH_GLOBS: tuple[str, ...] = (
    # Downstream layout: where an installed project carries the layer.
    ".agents/skills/yoke/**",
    ".claude/agents/yoke-*.md",
    ".claude/skills/yoke/**",
    ".codex/agents/yoke-*.toml",
    ".codex/skills/yoke/**",
    # Upstream layout: where Yoke's own repo authors the same content.
    "runtime/harness/claude/agents/yoke-*.md",
    "runtime/harness/codex/agents/yoke-*.toml",
    # Shipped reference docs — authored in the Yoke repo, installer-rendered
    # into managed projects at the same path. Long reference material (schema
    # catalogs, command references), not authored code, so exempt from the
    # authored-file line limit everywhere.
    ".yoke/docs/**",
)

# Rendered strategy views are untracked local renders (gitignored via the
# seeded contract), so they never enter authored-file enforcement and no
# built-in exception glob is needed; project additions come from
# .yoke/project.config.
DEFAULT_EXCEPTION_GLOBS: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileLinePolicy:
    limit: int
    exception_globs: tuple[str, ...]


def default_exception_globs() -> tuple[str, ...]:
    return DEFAULT_EXCEPTION_GLOBS


def tracked_generated_views() -> tuple[str, ...]:
    return TRACKED_GENERATED_VIEWS


def generated_path_globs() -> tuple[str, ...]:
    return GENERATED_PATH_GLOBS


def read_project_config(repo_root: Path | str) -> tuple[dict[str, str], tuple[str, ...]]:
    """Parse ``.yoke/project.config`` into scalars and exception globs.

    ``file_line_exception`` repeats, one glob per line; every other key is
    a scalar. A trailing ``# comment`` documents a value, so it is stripped.
    """
    path = Path(repo_root) / PROJECT_CONFIG_REL
    if not path.is_file():
        return {}, ()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}, ()
    scalars: dict[str, str] = {}
    exceptions: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.split("#", 1)[0].strip()
        if key == FILE_LINE_EXCEPTION_KEY:
            if value:
                exceptions.append(value)
        else:
            scalars[key] = value
    return scalars, tuple(exceptions)


def project_limit(repo_root: Path | str) -> int:
    """Resolve the authored-file line limit for ``repo_root``.

    An unset, malformed, or non-positive value falls back to
    :data:`DEFAULT_LIMIT`, so a typo can never silently relax the limit.
    """
    scalars, _ = read_project_config(repo_root)
    try:
        parsed = int(scalars.get(FILE_LINE_LIMIT_KEY, ""))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return parsed if parsed > 0 else DEFAULT_LIMIT


def project_exception_globs(repo_root: Path | str) -> tuple[str, ...]:
    _, exceptions = read_project_config(repo_root)
    return exceptions


def resolve_file_line_policy(repo_root: Path | str) -> FileLinePolicy:
    root = Path(repo_root)
    return FileLinePolicy(
        limit=project_limit(root),
        exception_globs=default_exception_globs() + project_exception_globs(root),
    )


__all__ = (
    "DEFAULT_EXCEPTION_GLOBS",
    "DEFAULT_LIMIT",
    "FILE_LINE_EXCEPTION_KEY",
    "FILE_LINE_LIMIT_KEY",
    "FileLinePolicy",
    "GENERATED_PATH_GLOBS",
    "PROJECT_CONFIG_REL",
    "TRACKED_GENERATED_VIEWS",
    "default_exception_globs",
    "generated_path_globs",
    "project_exception_globs",
    "project_limit",
    "read_project_config",
    "resolve_file_line_policy",
    "tracked_generated_views",
)

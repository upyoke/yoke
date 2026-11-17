"""Absolute path prefixes Yoke treats as free of path authority.

Two sides need the same list and they must not drift. The session-cwd guard
decides every read and write against it, and any Yoke writer that has to
hand an agent a path the agent's own guard will admit has to pick its
destination from it. A second copy is how a writer stages evidence
somewhere its reader is then refused for.
"""

from __future__ import annotations

import os
import tempfile

from yoke_contracts.hook_runner.bash_paths import (
    resolve_bash_path,
    is_under,
    client_path_facts,
    is_absolute,
    canonical_native_path,
)
from pathlib import Path


_ROOT = "/"


def _abs(*parts: str) -> str:
    return _ROOT + "/".join(parts)


TEMP_FAMILY_PREFIX = _abs("tmp")


#: The discard family (``/dev/null`` and siblings).
DEV_FAMILY_PREFIX = _abs("dev")

#: OS temp roots and the discard family. Home-derived free paths are
#: resolved per executing machine by the guard and are not listed here.
STATIC_FREE_PATH_PREFIXES = (
    TEMP_FAMILY_PREFIX,
    _abs("private", "tmp"),
    _abs("var", "folders"),
    _abs("private", "var", "folders"),
    DEV_FAMILY_PREFIX,
)


def free_path_prefixes(
    prefixes: tuple[str, ...] = STATIC_FREE_PATH_PREFIXES,
) -> tuple[str, ...]:
    """Include this machine's canonical TMPDIR only when explicitly absolute."""
    prefixes = tuple(resolve_bash_path(prefix) for prefix in prefixes)
    facts = client_path_facts()
    raw = (
        str(facts.get("tmpdir") or "")
        if facts is not None
        else os.environ.get("TMPDIR", "")
    )
    if not raw or not is_absolute(raw):
        return prefixes
    return (*prefixes, canonical_native_path(raw))


def is_under_free_path_prefix(
    target: str | Path,
    prefixes: tuple[str, ...] | None = None,
) -> bool:
    """Return whether *target* resolves under one of *prefixes*."""
    resolved = resolve_bash_path(str(target))
    return any(
        is_under(resolved, resolve_bash_path(prefix))
        for prefix in (free_path_prefixes() if prefixes is None else prefixes)
    )


def free_temp_root() -> Path:
    """Return a temp root every Yoke guard already admits.

    An absolute ``TMPDIR`` is admitted by its canonical path. Other OS temp
    roots outside the allowlist fall back to ``/tmp``.
    """
    root = Path(tempfile.gettempdir())
    return (
        root
        if is_under_free_path_prefix(root)
        else Path(resolve_bash_path(TEMP_FAMILY_PREFIX))
    )


def private_free_path(filename: str, *, prefix: str) -> Path:
    """Return *filename* inside a fresh private directory a guard admits.

    The temp root is shared with every other process on the machine and
    with every control plane this one talks to, so a path composed from
    a caller's own identifiers is not unique there: database ids repeat
    across universes, and a name another process can predict is a name
    it can occupy first. ``mkdtemp`` answers both -- it creates an
    unguessable directory owned by this user at mode 0700 and fails
    rather than reusing one -- so the caller keeps a readable filename
    without the enclosing path being guessable.

    Callers create the file themselves; only the directory exists here.
    """
    if not filename or Path(filename).parts != (filename,) or filename in {".", ".."}:
        raise ValueError(f"private scratch filename must be one segment: {filename!r}")
    root = free_temp_root()
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=root)) / filename


__all__ = [
    "DEV_FAMILY_PREFIX",
    "TEMP_FAMILY_PREFIX",
    "STATIC_FREE_PATH_PREFIXES",
    "free_path_prefixes",
    "free_temp_root",
    "is_under_free_path_prefix",
    "private_free_path",
]

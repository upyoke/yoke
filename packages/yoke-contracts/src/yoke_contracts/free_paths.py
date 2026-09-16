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
from pathlib import Path


_ROOT = "/"


def _abs(*parts: str) -> str:
    return os.path.join(_ROOT, *parts)


#: The discard family (``/dev/null`` and siblings).
DEV_FAMILY_PREFIX = _abs("dev")

#: OS temp roots and the discard family. Home-derived free paths are
#: resolved per executing machine by the guard and are not listed here.
STATIC_FREE_PATH_PREFIXES = (
    _abs("tmp"),
    _abs("private", "tmp"),
    _abs("var", "folders"),
    _abs("private", "var", "folders"),
    DEV_FAMILY_PREFIX,
)

#: Free by definition, so it is the fallback when the OS temp root is not.
FALLBACK_FREE_TEMP_ROOT = Path(_abs("tmp"))


def is_under_free_path_prefix(
    target: str | Path,
    prefixes: tuple[str, ...] = STATIC_FREE_PATH_PREFIXES,
) -> bool:
    """Return whether *target* resolves under one of *prefixes*."""
    resolved = str(Path(target).expanduser().resolve(strict=False))
    return any(
        resolved == prefix or resolved.startswith(prefix + os.sep)
        for prefix in prefixes
    )


def free_temp_root() -> Path:
    """Return a temp root every Yoke guard already admits.

    ``TMPDIR`` normally resolves under the allowlist already. An operator who
    has pointed it elsewhere would otherwise get a path their own guard
    refuses, so an out-of-allowlist temp root falls back to ``/tmp``.
    """
    root = Path(tempfile.gettempdir())
    return root if is_under_free_path_prefix(root) else FALLBACK_FREE_TEMP_ROOT


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
    "FALLBACK_FREE_TEMP_ROOT",
    "STATIC_FREE_PATH_PREFIXES",
    "free_temp_root",
    "is_under_free_path_prefix",
    "private_free_path",
]

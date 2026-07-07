"""Shared repo-root resolver — walks up from a start path looking for ``.git``.

Every module that needs the Yoke repo root should call ``find_repo_root()``
instead of using fragile ``Path(__file__).resolve().parents[N]`` indexing,
which breaks silently when files move to a different directory depth.
"""

from pathlib import Path
from typing import Optional


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk up from *start* (default: this file) until a ``.git`` marker is found.

    Returns the first ancestor directory containing ``.git``.
    Falls back to ``YOKE_REPO_ROOT`` env var, then ``git rev-parse``.
    Raises ``RuntimeError`` if no repo root can be determined.
    """
    import os

    # 1. Walk up from start path
    p = (start or Path(__file__)).resolve().parent
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent

    # 2. Env var fallback
    env_root = os.environ.get("YOKE_REPO_ROOT")
    if env_root:
        candidate = Path(env_root)
        if candidate.is_dir():
            return candidate

    # 3. git fallback
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass

    raise RuntimeError(
        "Cannot determine repo root: no .git ancestor, "
        "no YOKE_REPO_ROOT env var, and git rev-parse failed"
    )

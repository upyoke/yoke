"""Where Yoke's writable scratch root lives on this machine.

Selection order is ``YOKE_SCRATCH_ROOT``, then
``~/.yoke/config.json:temp_root``, then an OS-temp fallback; a
repo-local directory is never the default. Each candidate is probed by
writing to it, because a configured root that exists but is read-only is
the failure this resolver exists to survive: it warns and falls back
rather than letting every scratch write fail one by one.

Project, session, and run segments are layered on top of this root by
:mod:`yoke_core.domain.project_scratch_dir`.
"""

from __future__ import annotations

import tempfile
import os
import uuid
import warnings
from pathlib import Path

from yoke_core.domain import machine_config


ENV_KEY = "YOKE_SCRATCH_ROOT"


class ScratchRootResolutionError(RuntimeError):
    """Raised when no writable scratch root can be resolved."""


def global_scratch_root() -> Path:
    """Return the writable scratch root shared across ALL projects."""

    override = _override_root()
    if override is not None:
        resolved = _absolute_root(override)
        if ensure_writable_dir(resolved):
            return resolved
        warnings.warn(
            f"scratch root {resolved} is not writable; falling back to "
            f"{_fallback_base()}",
            RuntimeWarning,
            stacklevel=2,
        )

    fallback = _fallback_base()
    if ensure_writable_dir(fallback):
        return fallback
    raise ScratchRootResolutionError(
        f"Unable to create writable scratch root at {fallback}. "
        f"Set {ENV_KEY} to a writable path."
    )


def ensure_writable_dir(path: Path) -> bool:
    """Create *path* and prove it writable by round-tripping a probe file."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-test-{uuid.uuid4().hex}"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _override_root() -> str | None:
    env_value = os.environ.get(ENV_KEY, "").strip()
    if env_value:
        return env_value
    return machine_config.temp_root()


def _fallback_base() -> Path:
    base = Path(tempfile.gettempdir())
    if str(base).startswith("/var/folders/") and Path("/tmp").is_dir():
        base = Path("/tmp")
    return base / "yoke-scratch"


def _absolute_root(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return machine_config.yoke_home() / path


__all__ = [
    "ENV_KEY",
    "ScratchRootResolutionError",
    "ensure_writable_dir",
    "global_scratch_root",
]

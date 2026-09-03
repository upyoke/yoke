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

import uuid
import warnings
from pathlib import Path

from yoke_contracts.machine_config.scratch_roots import (
    fallback_scratch_root,
    scratch_root_candidates,
)


ENV_KEY = "YOKE_SCRATCH_ROOT"


class ScratchRootResolutionError(RuntimeError):
    """Raised when no writable scratch root can be resolved."""


def global_scratch_root() -> Path:
    """Return the writable scratch root shared across ALL projects."""

    candidates = scratch_root_candidates()
    fallback = candidates[-1]
    for candidate in candidates:
        if ensure_writable_dir(candidate):
            return candidate
        if candidate != fallback:
            warnings.warn(
                f"scratch root {candidate} is not writable; falling back to {fallback}",
                RuntimeWarning,
                stacklevel=2,
            )
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


__all__ = [
    "ENV_KEY",
    "fallback_scratch_root",
    "ScratchRootResolutionError",
    "ensure_writable_dir",
    "global_scratch_root",
]

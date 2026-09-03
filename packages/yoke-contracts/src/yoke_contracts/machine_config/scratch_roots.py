"""Where this machine's Yoke scratch tree can live, in resolution order.

The order lives here rather than in the engine because both sides need it
and only one of them may hold the engine: the writer picks the first
candidate it can write to, while a reader looking for a file some other
process already wrote has to consider every candidate that writer might
have chosen. A client package that reads scratch cannot reach into
``yoke_core``, so a second copy of the order would be the alternative, and
a reader whose order drifts from the writer's simply stops finding files.
"""

from __future__ import annotations

from pathlib import Path
import tempfile

from yoke_contracts.machine_config.runtime import effective_temp_root


#: The directory Yoke owns inside a shared OS temp base.
SCRATCH_DIR_NAME = "yoke-scratch"


def fallback_scratch_root() -> Path:
    """Return the OS-temp scratch root used when nothing is configured.

    macOS hands each user a private per-boot ``/var/folders`` temp dir. It is
    correct for one process and wrong for a shared root, because two Yoke
    processes belonging to the same person can land in different ones, so a
    real ``/tmp`` is preferred wherever it exists.
    """
    base = Path(tempfile.gettempdir())
    if str(base).startswith("/var/folders/") and Path("/tmp").is_dir():
        base = Path("/tmp")
    return base / SCRATCH_DIR_NAME


def scratch_root_candidates(path: str | Path | None = None) -> tuple[Path, ...]:
    """Return every root a scratch file could live under, best first."""
    return (Path(effective_temp_root(path)), fallback_scratch_root())


__all__ = [
    "SCRATCH_DIR_NAME",
    "fallback_scratch_root",
    "scratch_root_candidates",
]

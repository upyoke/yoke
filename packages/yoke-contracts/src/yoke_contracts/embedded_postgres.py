"""The pinned embedded-engine Postgres version and where its binaries live.

Client packages read this to locate the engine without importing the engine
package; :mod:`yoke_core.domain.postgres_binaries` fetches and resolves it.
"""

from __future__ import annotations

from pathlib import Path

#: The one pinned embedded-engine Postgres version (theseus-rs release tag:
#: upstream major.minor plus a build suffix).
POSTGRES_VERSION = "17.11.1"

#: Directory under the Yoke home holding fetched engines, one per version.
BINARIES_DIR_NAME = "postgres"


def engine_bin_dir(home: str | Path, version: str = POSTGRES_VERSION) -> Path:
    """The engine ``bin`` directory under the Yoke home *home*."""
    return Path(home) / BINARIES_DIR_NAME / version / "bin"


__all__ = ["BINARIES_DIR_NAME", "POSTGRES_VERSION", "engine_bin_dir"]

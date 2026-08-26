"""Resolve manifest-declared harness CLIs and their PATH directories."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Iterable

from yoke_contracts.harness_cli_manifest import (
    HARNESS_CLI_MANIFESTS,
    HarnessCliManifest,
)


@dataclass(frozen=True)
class HarnessCliResolution:
    harness_id: str
    surface_id: str
    executable: str
    path: str | None
    source: str

    @property
    def directory(self) -> str | None:
        return str(Path(self.path).parent) if self.path else None

    def to_json(self) -> dict[str, str | None]:
        return {
            "harness_id": self.harness_id,
            "surface_id": self.surface_id,
            "executable": self.executable,
            "path": self.path,
            "directory": self.directory,
            "source": self.source,
        }


def _bundled_resolution(manifest: HarnessCliManifest) -> str | None:
    for raw in manifest.bundled_candidates:
        candidate = Path(raw).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def resolve_harness_clis(
    path_value: str | None,
    *,
    manifests: Iterable[HarnessCliManifest] = HARNESS_CLI_MANIFESTS,
) -> tuple[HarnessCliResolution, ...]:
    resolutions = []
    for manifest in manifests:
        found = shutil.which(manifest.executable, path=path_value)
        source = "path"
        if not found:
            found = _bundled_resolution(manifest)
            source = "bundled" if found else "missing"
        resolutions.append(
            HarnessCliResolution(
                manifest.harness_id,
                manifest.surface_id,
                manifest.executable,
                found,
                source,
            )
        )
    return tuple(resolutions)


def managed_path_directories(
    tool_bin_dir: str,
    harness_clis: Iterable[HarnessCliResolution],
) -> tuple[str, ...]:
    candidates = [tool_bin_dir]
    candidates.extend(
        resolution.directory for resolution in harness_clis if resolution.directory
    )
    return tuple(
        dict.fromkeys(str(Path(candidate).expanduser()) for candidate in candidates)
    )


__all__ = [
    "HarnessCliResolution",
    "managed_path_directories",
    "resolve_harness_clis",
]

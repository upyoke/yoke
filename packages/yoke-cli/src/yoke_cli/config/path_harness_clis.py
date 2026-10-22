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


@dataclass(frozen=True)
class ResolvedNativeCli:
    """The executable and the installation route that supplied it."""

    path: str
    source: str


def resolve_native_cli_source(
    command_name: str,
    *,
    path_value: str | None = None,
    manifests: Iterable[HarnessCliManifest] | None = None,
) -> ResolvedNativeCli | None:
    """Resolve explicit, PATH, then manifest-declared bundled executables."""
    if os.sep in command_name:
        candidate = Path(command_name)
        return (
            ResolvedNativeCli(command_name, "explicit")
            if candidate.is_file() and os.access(candidate, os.X_OK)
            else None
        )
    found = shutil.which(command_name, path=path_value)
    if found:
        return ResolvedNativeCli(found, "path")
    for manifest in HARNESS_CLI_MANIFESTS if manifests is None else manifests:
        if manifest.executable != command_name:
            continue
        for raw in manifest.bundled_candidates:
            candidate = Path(raw).expanduser()
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return ResolvedNativeCli(str(candidate), "bundled")
    return None


def resolve_harness_clis(
    path_value: str | None,
    *,
    manifests: Iterable[HarnessCliManifest] = HARNESS_CLI_MANIFESTS,
) -> tuple[HarnessCliResolution, ...]:
    manifests = tuple(manifests)
    resolutions = []
    for manifest in manifests:
        resolved = resolve_native_cli_source(
            manifest.executable, path_value=path_value, manifests=manifests
        )
        resolutions.append(
            HarnessCliResolution(
                manifest.harness_id,
                manifest.surface_id,
                manifest.executable,
                resolved.path if resolved else None,
                resolved.source if resolved else "missing",
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
    "ResolvedNativeCli",
    "resolve_native_cli_source",
    "managed_path_directories",
    "resolve_harness_clis",
]

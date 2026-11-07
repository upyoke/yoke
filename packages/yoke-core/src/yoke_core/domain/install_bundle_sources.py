"""Standalone release inputs and installed harness manifest destinations."""

from pathlib import Path

from yoke_contracts.project_contract.managed_block import MANAGED_BLOCK_END
from yoke_contracts.project_contract.source_installed_views import (
    HARNESS_MANIFEST_SOURCES,
    harness_manifest_view,
)
from yoke_core.domain.install_bundle import InstallBundleError


INSTALL_BUNDLE_SOURCE_FILES = ("AGENTS.md", *HARNESS_MANIFEST_SOURCES)


class InstallBundleTreeError(InstallBundleError):
    """A release source cannot be materialized; the message teaches recovery."""


def source_file_bytes(source: Path) -> bytes:
    """Keep doctrine project-neutral and manifests byte-identical to the release."""
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise InstallBundleTreeError(
            f"install_bundle_source_unreadable: {source}. "
            "Restore this release's bundle source file and retry."
        ) from exc
    if source.name != "AGENTS.md":
        return data
    marker = MANAGED_BLOCK_END.encode("utf-8")
    end = data.find(marker)
    if end < 0:
        raise InstallBundleTreeError(
            f"install-bundle root source lacks managed-block boundary: {source}. "
            "Restore the managed AGENTS.md boundary and retry."
        )
    return data[: end + len(marker)] + b"\n"


def harness_manifest_files(root: Path) -> list[dict[str, str]]:
    """Publish renderer-owned release bytes through the existing managed files list."""
    entries = []
    for rel in HARNESS_MANIFEST_SOURCES:
        try:
            content = source_file_bytes(root / rel).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InstallBundleTreeError(
                f"install_bundle_manifest_invalid_encoding: {root / rel}. "
                "Restore this release's UTF-8 harness manifest and retry."
            ) from exc
        entries.append(
            {
                "path": harness_manifest_view(rel),
                "content": content,
            }
        )
    return entries

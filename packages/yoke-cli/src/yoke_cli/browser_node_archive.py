"""Extract checksum-verified Node distributions without trusting archive paths."""

from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def unpack_release(
    archive: Path, staging: Path, destination: Path, *, error_type
) -> None:
    """Validate the archive layout and replace the managed version."""
    extract_root = staging / "extracted"
    extract_root.mkdir()
    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as handle:
                for entry in handle.infolist():
                    path = PurePosixPath(entry.filename.replace("\\", "/"))
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or ":" in entry.filename
                    ):
                        raise ValueError(f"unsafe Node archive path: {entry.filename}")
                handle.extractall(extract_root)
        else:
            with tarfile.open(archive, "r:gz") as handle:
                handle.extractall(extract_root, filter="tar")
        entries = list(extract_root.iterdir())
        if len(entries) != 1 or not entries[0].is_dir():
            raise ValueError("expected one top-level Node distribution directory")
        if destination.exists():
            shutil.rmtree(destination)
        entries[0].replace(destination)
    except (tarfile.TarError, zipfile.BadZipFile, OSError, ValueError) as exc:
        raise error_type(
            f"the downloaded Node.js archive could not be unpacked: {exc}",
            code="node_archive_unusable",
            recovery=(
                f"check free space and write access under {destination.parent}, "
                "then rerun `yoke qa browser setup`; a repeated invalid layout "
                "requires correcting the pinned release"
            ),
        ) from exc

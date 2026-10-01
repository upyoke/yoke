"""Read Cursor's embedded version file without executing an AppImage."""

from __future__ import annotations

from pathlib import Path
import shutil
import struct
import subprocess
from typing import Callable

from yoke_core.domain.json_helper import loads_text

# Type-2 AppImages append SquashFS after a small ELF runtime.
_RUNTIME_SCAN_BYTES = 4 * 1024 * 1024
CURSOR_VERSION_FILE = "usr/share/cursor/resources/app/package.json"


def cursor_version(text: str) -> str:
    try:
        payload = loads_text(text)
    except ValueError as exc:
        raise ValueError(
            "cursor_version_invalid: reinstall Cursor; package.json is not valid JSON"
        ) from exc
    # `version` is the upstream VS Code version, not Cursor's release version.
    version = payload.get("cursorVersion") if isinstance(payload, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError(
            "cursor_version_missing: reinstall Cursor; package.json must name cursorVersion"
        )
    return version.strip()


def read_appimage_version(
    image: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = 10,
) -> str:
    with image.open("rb") as handle:
        prefix = handle.read(_RUNTIME_SCAN_BYTES)
    if prefix[:4] != b"\x7fELF" or prefix[8:11] != b"AI\x02":
        raise ValueError(
            "cursor_appimage_invalid: replace it with an official Type-2 AppImage"
        )
    offset = prefix.find(b"hsqs")
    while offset >= 0:
        if len(prefix) >= offset + 32 and struct.unpack_from(
            "<HH", prefix, offset + 28
        ) == (4, 0):
            break
        offset = prefix.find(b"hsqs", offset + 4)
    if offset < 0:
        raise ValueError(
            "cursor_appimage_layout_unknown: install Cursor's .deb or .rpm package instead"
        )
    reader = shutil.which("unsquashfs")
    if not reader:
        raise RuntimeError(
            "cursor_appimage_reader_missing: install squashfs-tools and retry the probe"
        )
    completed = runner(
        [reader, "-o", str(offset), "-cat", str(image), CURSOR_VERSION_FILE],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or "no output").strip()[:160]
        raise RuntimeError(
            f"cursor_appimage_metadata_unreadable: {detail}; reinstall the AppImage and retry"
        )
    return cursor_version(completed.stdout)

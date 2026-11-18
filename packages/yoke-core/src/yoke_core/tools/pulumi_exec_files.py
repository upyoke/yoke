"""Owner-only file writers for bounded Pulumi execution."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from typing import Any, TextIO

from yoke_contracts import windows_private_directory
from yoke_contracts.owner_private_path import create_owner_private_directory


def _new_private_descriptor(path: Path) -> int:
    """Create a new file that is owner-only before any byte is written."""
    if os.name == "nt":
        return windows_private_directory.create_private_file(path)
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)


def write_owner_only(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = _new_private_descriptor(path)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


def new_owner_only_output(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return os.fdopen(_new_private_descriptor(path), "w", encoding="utf-8")


@contextmanager
def owner_only_temp_root() -> Iterator[Path]:
    """Yield a private scratch root that is removed with everything below it."""
    with tempfile.TemporaryDirectory(prefix="yoke-pulumi-exec-") as raw_temp:
        yield create_owner_private_directory(Path(raw_temp) / "work")


__all__ = ["new_owner_only_output", "owner_only_temp_root", "write_owner_only"]

"""Shared text-file writer for generated project views."""

from __future__ import annotations

import os
import time
from pathlib import Path


def write_live_text(path: Path, content: str) -> None:
    """Refresh generated text while preserving open-editor file identity."""

    data = content.encode("utf-8")
    if path.exists():
        with path.open("r+b") as handle:
            handle.seek(0)
            handle.write(data)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        os.utime(path, None)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp_path.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        os.utime(path, None)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


__all__ = ["write_live_text"]

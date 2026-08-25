"""Batched ``git cat-file`` reads for project snapshot scanning."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Tuple

BLOB_BATCH_SIZE = 250

ProgressFn = Callable[[int, int], None]


class BlobScanError(RuntimeError):
    """The checkout could not yield blob contents for a snapshot scan."""


def blob_sources(
    repo_root: Path,
    blobs: Sequence[Tuple[str, str]],
    on_progress: Optional[ProgressFn] = None,
) -> Dict[str, str]:
    """Return UTF-8 blob text keyed by path, in batches with progress."""
    sources: Dict[str, str] = {}
    if not blobs:
        return sources
    total = len(blobs)
    for start in range(0, total, BLOB_BATCH_SIZE):
        batch = blobs[start : start + BLOB_BATCH_SIZE]
        sources.update(_blob_sources_batch(repo_root, batch))
        done = min(start + BLOB_BATCH_SIZE, total)
        if on_progress is not None:
            on_progress(done, total)
    return sources


def _blob_sources_batch(
    repo_root: Path,
    blobs: Sequence[Tuple[str, str]],
) -> Dict[str, str]:
    sources: Dict[str, str] = {}
    try:
        proc = subprocess.Popen(
            ["git", "-C", str(repo_root), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise BlobScanError("git is required for snapshot sync") from exc
    request = "".join(f"{sha}\n" for sha, _path in blobs).encode("ascii")
    stdout, stderr = proc.communicate(request)
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise BlobScanError(f"git cat-file --batch failed in {repo_root}: {detail}")
    offset = 0
    for expected_sha, path in blobs:
        try:
            line_end = stdout.index(b"\n", offset)
        except ValueError as exc:
            raise BlobScanError(
                f"git cat-file ended before blob header for {path}"
            ) from exc
        header = stdout[offset:line_end].decode("ascii", errors="replace")
        parts = header.split()
        if len(parts) != 3 or parts[0] != expected_sha or parts[1] != "blob":
            raise BlobScanError(
                f"git cat-file returned unexpected header for {path}: {header}"
            )
        size = int(parts[2])
        start = line_end + 1
        end = start + size
        data = stdout[start:end]
        try:
            sources[path] = data.decode("utf-8")
        except UnicodeDecodeError:
            sources[path] = ""
        offset = end + 1
    return sources

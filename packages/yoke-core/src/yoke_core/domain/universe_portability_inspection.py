"""Bounded inspection and safe catalog receipts for universe archives."""

from __future__ import annotations

import hashlib
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from yoke_core.domain.postgres_client_runtime import postgres_executable
from yoke_core.domain.universe_portability_catalog import (
    catalog_data_targets,
    validate_catalog,
)
from yoke_core.domain.universe_portability_common import (
    ARCHIVE_MAGIC,
    CATALOG_BYTES,
    DEFAULT_ARCHIVE_TIMEOUT_S,
    DEFAULT_MAX_ARCHIVE_BYTES,
    PUMP_CHUNK_BYTES,
    ArchiveInspection,
    ArchiveInvalidError,
    ArchiveTooLargeError,
    bounded_diagnostic_reader,
    subprocess_base_env,
    terminate,
)


DUMPED_FROM_RE = re.compile(r"^;\s+Dumped from database version:\s+(.+)$", re.M)
DUMPED_BY_RE = re.compile(r"^;\s+Dumped by pg_dump version:\s+(.+)$", re.M)


def catalog_reader(
    stream: object,
    sink: bytearray,
    errors: list[BaseException],
    *,
    max_bytes: int = CATALOG_BYTES,
) -> None:
    """Drain one catalog with a hard memory ceiling."""
    try:
        while True:
            chunk = stream.read(PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
            if not chunk:
                return
            if len(sink) + len(chunk) > max_bytes:
                raise ArchiveInvalidError(
                    "the universe archive catalog exceeds the inspection limit"
                )
            sink.extend(chunk)
    except BaseException as exc:  # noqa: BLE001 - crosses a worker thread
        errors.append(exc)
    finally:
        stream.close()  # type: ignore[attr-defined]


def archive_catalog(
    archive: Path,
    *,
    executable: str,
    timeout_s: float,
) -> str:
    """Return bounded pg_restore catalog text without buffering stderr."""
    try:
        process = subprocess.Popen(
            [executable, "--list", str(archive)],
            env=subprocess_base_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ArchiveInvalidError(
            f"the universe archive could not be inspected: {exc}"
        ) from exc
    assert process.stdout is not None and process.stderr is not None
    catalog_bytes = bytearray()
    diagnostic = bytearray()
    errors: list[BaseException] = []
    workers = (
        threading.Thread(
            target=catalog_reader,
            args=(process.stdout, catalog_bytes, errors),
            daemon=True,
        ),
        threading.Thread(
            target=bounded_diagnostic_reader,
            args=(process.stderr, diagnostic),
            daemon=True,
        ),
    )
    for worker in workers:
        worker.start()
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        terminate(process)
        raise ArchiveInvalidError(
            "the universe archive could not be inspected: timed out"
        ) from exc
    finally:
        terminate(process)
        for worker in workers:
            worker.join(timeout=5)
    if errors:
        error = errors[0]
        if isinstance(error, ArchiveInvalidError):
            raise error
        raise ArchiveInvalidError(
            "the universe archive catalog could not be read"
        ) from error
    if process.returncode != 0:
        detail = bytes(diagnostic).decode("utf-8", errors="replace")
        tail = detail.strip().splitlines()[-1:]
        raise ArchiveInvalidError(
            "the universe archive catalog is corrupt or unreadable"
            + (f": {tail[0]}" if tail else "")
        )
    try:
        return bytes(catalog_bytes).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArchiveInvalidError(
            "the universe archive catalog is not valid UTF-8"
        ) from exc


def inspect_archive_with_catalog(
    path: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: float = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
    executable_resolver: Callable[[str], str] = postgres_executable,
) -> tuple[ArchiveInspection, str]:
    """Validate size, magic, versions, and the safe TOC boundary."""
    archive = Path(path)
    if not archive.is_file():
        raise ArchiveInvalidError("the universe archive is not a regular file")
    size = archive.stat().st_size
    if size <= 0:
        raise ArchiveInvalidError("the universe archive is empty")
    if size > max_bytes:
        raise ArchiveTooLargeError(
            f"the universe archive is {size} bytes; limit is {max_bytes} bytes"
        )
    with archive.open("rb") as stream:
        if stream.read(len(ARCHIVE_MAGIC)) != ARCHIVE_MAGIC:
            raise ArchiveInvalidError(
                "the artifact is not a pg_dump custom-format universe archive"
            )
    executable = pg_restore or executable_resolver("pg_restore")
    catalog = archive_catalog(archive, executable=executable, timeout_s=timeout_s)
    table_entries = validate_catalog(catalog)
    dumped_from = DUMPED_FROM_RE.search(catalog)
    dumped_by = DUMPED_BY_RE.search(catalog)
    if dumped_from is None or dumped_by is None:
        raise ArchiveInvalidError(
            "the archive catalog omits its PostgreSQL version headers"
        )
    tables, sequences = catalog_data_targets(catalog)
    inspection = ArchiveInspection(
        path=archive,
        size_bytes=size,
        dumped_from_postgres=dumped_from.group(1).strip(),
        dumped_by_pg_dump=dumped_by.group(1).strip(),
        table_entries=table_entries,
        archive_sha256=file_sha256(archive),
        catalog_tables=tuple(sorted(tables)),
        catalog_sequences=tuple(sorted(sequences)),
        catalog_digest=catalog_digest(catalog),
    )
    return inspection, catalog


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(PUMP_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def catalog_digest(catalog: str) -> str:
    tables, sequences = catalog_data_targets(catalog)
    canonical = (
        "\n".join(sorted(tables)) + "\n--sequences--\n" + "\n".join(sorted(sequences))
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def archive_catalog_receipt(inspection: ArchiveInspection) -> dict[str, object]:
    """Return the exact portable data catalog without archive contents."""
    return {
        "archive_sha256": inspection.archive_sha256,
        "bytes": inspection.size_bytes,
        "tables": list(inspection.catalog_tables),
        "sequences": list(inspection.catalog_sequences),
        "catalog_digest": inspection.catalog_digest,
        "table_entries": inspection.table_entries,
    }


def inspect_archive(
    path: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: float = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
    executable_resolver: Callable[[str], str] = postgres_executable,
) -> ArchiveInspection:
    """Validate size, bounded catalog, versions, schema, and TOC kinds."""
    inspection, _catalog = inspect_archive_with_catalog(
        path,
        max_bytes=max_bytes,
        timeout_s=timeout_s,
        pg_restore=pg_restore,
        executable_resolver=executable_resolver,
    )
    return inspection


__all__ = [
    "archive_catalog",
    "archive_catalog_receipt",
    "catalog_digest",
    "catalog_reader",
    "file_sha256",
    "inspect_archive",
    "inspect_archive_with_catalog",
]

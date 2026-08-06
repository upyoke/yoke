"""Shared limits, errors, and process helpers for universe portability."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping, Optional

from psycopg import conninfo, pq


ARCHIVE_FORMAT = "pg_dump-custom"
ARCHIVE_MAGIC = b"PGDMP"
DEFAULT_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
DEFAULT_ARCHIVE_TIMEOUT_S = 600
DEFAULT_MAX_RESTORE_EXPANSION = 16

PUMP_CHUNK_BYTES = 1 << 20
DIAGNOSTIC_BYTES = 32 * 1024
CATALOG_BYTES = 16 * 1024 * 1024


class UniversePortabilityError(RuntimeError):
    """A portable universe operation was refused or failed safely."""


class ArchiveTooLargeError(UniversePortabilityError):
    """The archive exceeds the configured body/artifact ceiling."""


class ArchiveInvalidError(UniversePortabilityError):
    """The artifact is not a safe, listable custom-format universe dump."""


class ArchiveCompatibilityError(UniversePortabilityError):
    """A restored archive is not compatible with the target engine schema."""


@dataclass(frozen=True)
class ArchiveInspection:
    path: Path
    size_bytes: int
    dumped_from_postgres: str
    dumped_by_pg_dump: str
    table_entries: int
    archive_sha256: str = ""
    catalog_tables: tuple[str, ...] = ()
    catalog_sequences: tuple[str, ...] = ()
    catalog_digest: str = ""


def remaining_timeout(deadline: float, operation: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UniversePortabilityError(
            f"universe {operation} exhausted its end-to-end timeout"
        )
    return max(0.001, remaining)


def subprocess_base_env() -> dict[str, str]:
    """Return the small non-secret environment allowed for Postgres clients."""
    allowed = (
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "SYSTEMROOT",
        "TMP",
        "TMPDIR",
        "TEMP",
    )
    return {key: os.environ[key] for key in allowed if key in os.environ}


def postgres_client_env(
    dsn: str,
    *,
    base: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Translate a libpq DSN into ``PG*`` env without putting it in argv."""
    parsed = conninfo.conninfo_to_dict(dsn)
    env: MutableMapping[str, str] = dict(
        subprocess_base_env() if base is None else base
    )
    for key in tuple(env):
        if key.startswith("PG") or key.startswith("YOKE_"):
            env.pop(key, None)
    env_by_keyword = {
        option.keyword.decode(): option.envvar.decode()
        for option in pq.Conninfo.get_defaults()
        if option.envvar
    }
    unsupported = sorted(set(parsed).difference(env_by_keyword))
    if unsupported:
        raise UniversePortabilityError(
            "the database connection uses libpq options without an environment"
            f" mapping: {', '.join(unsupported)}"
        )
    for key, value in parsed.items():
        if value is not None:
            env[env_by_keyword[key]] = str(value)
    return dict(env)


def bounded_diagnostic_reader(stream: object, sink: bytearray) -> None:
    """Drain a subprocess diagnostic pipe while retaining only its tail."""
    try:
        while True:
            chunk = stream.read(PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
            if not chunk:
                return
            sink.extend(chunk)
            if len(sink) > DIAGNOSTIC_BYTES:
                del sink[:-DIAGNOSTIC_BYTES]
    finally:
        stream.close()  # type: ignore[attr-defined]


def terminate(process: subprocess.Popen[bytes]) -> None:
    """Stop one child process without allowing teardown to hang."""
    if process.poll() is not None:
        return
    process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


__all__ = [
    "ARCHIVE_FORMAT",
    "ARCHIVE_MAGIC",
    "ArchiveCompatibilityError",
    "ArchiveInspection",
    "ArchiveInvalidError",
    "ArchiveTooLargeError",
    "CATALOG_BYTES",
    "DEFAULT_ARCHIVE_TIMEOUT_S",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "DEFAULT_MAX_RESTORE_EXPANSION",
    "DIAGNOSTIC_BYTES",
    "PUMP_CHUNK_BYTES",
    "UniversePortabilityError",
    "bounded_diagnostic_reader",
    "postgres_client_env",
    "remaining_timeout",
    "subprocess_base_env",
    "terminate",
]

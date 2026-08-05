"""Durable, private Postgres restore-point dumps."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional

from yoke_core.domain import runtime_settings

_PARTIAL_SUFFIX = ".sql.partial"


def dump_postgres_to_directory(dsn: str, reason: str, backup_dir: Path) -> str:
    """Publish a credential-safe ``pg_dump`` restore point atomically.

    The caller chooses the directory because operator, boot-time, and external
    project authorities have different durable roots. The connection travels
    through libpq environment variables, never process arguments.
    """
    from yoke_core.domain import postgres_client_runtime, universe_portability

    executable = postgres_client_runtime.postgres_executable("pg_dump")
    client_env = universe_portability.postgres_client_env(dsn)
    root = Path(backup_dir)
    _ensure_private_directory(root)
    output, partial, destination = _private_output(root, reason)
    timeout = runtime_settings.get_seconds(
        "backup_subprocess_timeout_seconds",
        60,
    )
    published = False
    try:
        try:
            with output:
                result = subprocess.run(
                    [
                        executable,
                        "--no-owner",
                        "--no-privileges",
                    ],
                    env=client_env,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout,
                )
        except OSError as exc:
            raise RuntimeError(
                f"pg_dump backup could not start using {executable}: {exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"pg_dump backup timed out after {timeout}s using {executable}"
            ) from exc
        if result.returncode != 0 or not partial.is_file():
            diagnostic = _safe_diagnostic(
                result.stderr,
                secrets=(dsn, client_env.get("PGPASSWORD", "")),
            )
            version_help = ""
            if "server version mismatch" in str(result.stderr or "").casefold():
                version_help = (
                    "; select a pg_dump client whose major version is at least "
                    "the reported server major version"
                )
            raise RuntimeError(
                f"pg_dump backup failed using {executable}: {diagnostic}{version_help}"
            )
        if partial.stat().st_size == 0:
            raise RuntimeError(f"pg_dump backup file is empty using {executable}")
        partial.chmod(0o600)
        _fsync_file(partial)
        os.replace(partial, destination)
        published = True
        _fsync_directory(root)
        return str(destination)
    except Exception:
        if published:
            destination.unlink(missing_ok=True)
        raise
    finally:
        partial.unlink(missing_ok=True)


def _ensure_private_directory(backup_dir: Path) -> None:
    if backup_dir.is_symlink():
        raise RuntimeError(
            f"Postgres backup directory must not be a symlink: {backup_dir}"
        )
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if backup_dir.is_symlink() or not backup_dir.is_dir():
        raise RuntimeError(
            f"Postgres backup path is not a private directory: {backup_dir}"
        )
    backup_dir.chmod(0o700)
    if os.name != "nt" and stat.S_IMODE(backup_dir.stat().st_mode) != 0o700:
        raise RuntimeError(
            f"Postgres backup directory permissions are not 0700: {backup_dir}"
        )


def _private_output(backup_dir: Path, reason: str) -> tuple[BinaryIO, Path, Path]:
    safe_reason = _sanitize_reason(reason)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    prefix = f".postgres.{timestamp}.{safe_reason}."
    descriptor, partial_name = tempfile.mkstemp(
        prefix=prefix,
        suffix=_PARTIAL_SUFFIX,
        dir=backup_dir,
    )
    partial = Path(partial_name)
    published_name = partial.name[1 : -len(_PARTIAL_SUFFIX)] + ".sql"
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        output = os.fdopen(descriptor, "wb")
    except Exception:
        os.close(descriptor)
        partial.unlink(missing_ok=True)
        raise
    return output, partial, backup_dir / published_name


def _safe_diagnostic(stderr: Optional[str], *, secrets: tuple[str, ...]) -> str:
    diagnostic = str(stderr or "")
    selected = sorted(
        {value for value in secrets if value},
        key=len,
        reverse=True,
    )
    for secret in selected:
        diagnostic = diagnostic.replace(secret, "<redacted-secret>")
    flattened = " ".join(diagnostic.split())
    return flattened[-800:] or "no stderr diagnostic"


def _sanitize_reason(reason: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", reason.strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "rollback"


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["dump_postgres_to_directory"]

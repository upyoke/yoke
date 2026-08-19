"""Copy a live database onto the local rehearsal cluster."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Sequence

from yoke_core.domain import postgres_cluster
from yoke_core.domain.postgres_cluster import ClusterSpec

DUMP_TIMEOUT_SECONDS = 3600
RESTORE_TIMEOUT_SECONDS = 900
DUMP_ATTEMPTS = 3

DUMP_RETRY_MARKERS = (
    "ssl syscall error",
    "eof detected",
    "connection reset",
    "server closed the connection",
    "could not receive data",
    "could not send data",
)

_DUMP_KEEPALIVE_ENV = {
    "PGKEEPALIVES": "1",
    "PGKEEPALIVES_IDLE": "30",
    "PGKEEPALIVES_INTERVAL": "10",
    "PGKEEPALIVES_COUNT": "3",
}


def dump_env(base: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    env = dict(base if base is not None else os.environ)
    for key, value in _DUMP_KEEPALIVE_ENV.items():
        env.setdefault(key, value)
    return env


def is_transient_dump_error(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in DUMP_RETRY_MARKERS)


def run_transfer(
    argv: Sequence[str],
    *,
    redact: str = "",
    timeout: int,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    try:
        result = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=None if env is None else dict(env),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{Path(argv[0]).name} timed out after {timeout}s"
        ) from exc
    if result.returncode == 0:
        return
    stderr = (result.stderr or "").strip()
    if redact:
        stderr = stderr.replace(redact, "<dsn>")
    raise RuntimeError(f"{Path(argv[0]).name} failed ({result.returncode}): {stderr}")


def dump_database(spec: ClusterSpec, source_dsn: str, dump: Path) -> None:
    argv = [
        postgres_cluster.binary(spec, "pg_dump"),
        "--no-owner",
        "--no-privileges",
        "--compress=1",
        "--format=custom",
        "--file",
        str(dump),
        source_dsn,
    ]
    last_error: Exception | None = None
    for attempt in range(1, DUMP_ATTEMPTS + 1):
        try:
            run_transfer(
                argv,
                redact=source_dsn,
                timeout=DUMP_TIMEOUT_SECONDS,
                env=dump_env(),
            )
            return
        except RuntimeError as exc:
            last_error = exc
            dump.unlink(missing_ok=True)
            if attempt == DUMP_ATTEMPTS or not is_transient_dump_error(str(exc)):
                raise
    raise last_error  # pragma: no cover


def create_copy(spec: ClusterSpec, copy_name: str) -> None:
    run_transfer(
        [
            postgres_cluster.binary(spec, "createdb"),
            "-h",
            str(spec.sock_dir),
            "-U",
            spec.superuser,
            copy_name,
        ],
        timeout=RESTORE_TIMEOUT_SECONDS,
    )


def restore_copy(spec: ClusterSpec, copy_name: str, dump: Path) -> None:
    run_transfer(
        [
            postgres_cluster.binary(spec, "pg_restore"),
            "-h",
            str(spec.sock_dir),
            "-U",
            spec.superuser,
            "-d",
            copy_name,
            "--no-owner",
            "--no-privileges",
            str(dump),
        ],
        timeout=RESTORE_TIMEOUT_SECONDS,
    )


def drop_copy(spec: ClusterSpec, copy_name: str) -> None:
    subprocess.run(
        [
            postgres_cluster.binary(spec, "dropdb"),
            "-h",
            str(spec.sock_dir),
            "-U",
            spec.superuser,
            "--if-exists",
            "--force",
            copy_name,
        ],
        capture_output=True,
        text=True,
        timeout=RESTORE_TIMEOUT_SECONDS,
    )

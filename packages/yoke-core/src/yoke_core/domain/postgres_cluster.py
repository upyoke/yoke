"""Shared initdb/pg_ctl choreography for Yoke-managed Postgres clusters.

One cluster-lifecycle core, two frontends:

* :mod:`yoke_core.tools.pg_testcluster` — the disposable test cluster
  (installed embedded binaries or PATH, scratch root, durability turned off).
* :mod:`yoke_core.domain.local_universe` — the embedded local-mode engine
  (machine-runtime binaries, durable data under ``~/.yoke/``).

Both frontends describe their cluster with a :class:`ClusterSpec` and call
the same functions here, so the initdb/pg_ctl mechanics never fork. Every
managed cluster is unix-socket-only (``listen_addresses=''``) with trust
auth on the socket. The socket directory is private to the current user; it
normally lives inside the cluster root, but may use a short external path on
platforms with restrictive Unix-socket path limits. No TCP port is ever
claimed.
"""

from __future__ import annotations

from yoke_contracts.machine_config.directories import create_private_directory

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from yoke_core.domain.postgres_cluster_process import _env, _run, executable

#: The in-socket-directory port suffix Postgres uses to name the socket
#: file (``.s.PGSQL.<port>``). With ``listen_addresses=''`` no TCP socket
#: is bound, so this never collides with another server: each managed
#: cluster owns a private socket directory.
SOCKET_PORT = 5432

# sun_path is 104 bytes on macOS/BSD and 108 on Linux, including the trailing NUL.
_MAX_POSTGRES_SOCKET_PATH_BYTES = 107 if sys.platform.startswith("linux") else 103


class PostgresClusterError(RuntimeError):
    """A managed cluster's filesystem boundary is unsafe or unavailable."""


@dataclass(frozen=True)
class ClusterSpec:
    """Everything the lifecycle core needs to manage one cluster.

    ``bin_dir=None`` resolves ``initdb``/``pg_ctl``/``psql``/``pg_isready``
    from ``PATH``; a concrete directory pins them (embedded binaries).
    ``server_settings`` render as ``-c name=value`` server options.
    ``stop_mode`` is ``fast`` for durable clusters (checkpoint on stop)
    and ``immediate`` for throwaway ones.
    """

    root: Path
    superuser: str
    server_settings: Tuple[Tuple[str, str], ...] = ()
    bin_dir: Optional[Path] = None
    stop_mode: str = "fast"
    socket_dir: Optional[Path] = None

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def sock_dir(self) -> Path:
        return self.socket_dir if self.socket_dir is not None else self.root / "sock"

    @property
    def log_file(self) -> Path:
        return self.root / "server.log"


def socket_dir_for_root(root: Path) -> Optional[Path]:
    """Return a stable short socket directory only when ``root / sock`` is too long."""
    socket_name = f".s.PGSQL.{SOCKET_PORT}"
    if len(os.fsencode(root / "sock" / socket_name)) <= _MAX_POSTGRES_SOCKET_PATH_BYTES:
        return None
    uid = getattr(os, "getuid", lambda: 0)()
    digest = hashlib.sha256(os.fsencode(root.absolute())).hexdigest()[:12]
    candidates = (Path(tempfile.gettempdir()), Path("/tmp"))
    bases = {
        os.fsencode(candidate): candidate
        for candidate in candidates
        if candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)
    }
    if not bases:
        raise PostgresClusterError(
            "no writable temporary directory is available for a Postgres Unix "
            f"socket (cluster root {root}). Create a writable temp directory and retry."
        )
    base = min(
        bases.values(),
        key=lambda candidate: (len(os.fsencode(candidate)), os.fsencode(candidate)),
    )
    fallback = base / f"yoke-pg-{uid}-{digest}"
    if len(os.fsencode(fallback / socket_name)) > _MAX_POSTGRES_SOCKET_PATH_BYTES:
        raise PostgresClusterError(
            "cluster root and temp directory are too long for a Postgres Unix "
            f"socket (cluster root {root}). Choose a shorter cluster root and retry."
        )
    return fallback


def binary(spec: ClusterSpec, name: str) -> str:
    """Resolve one Postgres executable per the spec's binary source."""
    return executable(spec.bin_dir, name)


def dsn(spec: ClusterSpec, dbname: str = "postgres") -> str:
    """Key/value DSN for the cluster over its unix socket."""
    return f"host={spec.sock_dir} user={spec.superuser} dbname={dbname}"


def psql(
    spec: ClusterSpec,
    sql: str,
    dbname: str = "postgres",
    *,
    statement_timeout_ms: int | None = None,
) -> subprocess.CompletedProcess:
    """Run *sql* through ``psql``, optionally bounding how long it may block.

    ``statement_timeout_ms`` travels as a connection option rather than a
    leading ``SET``: ``psql -c`` wraps a multi-statement string in one
    transaction, and ``DROP DATABASE`` cannot run inside a transaction block.
    A bounded statement fails loudly instead of parking on a lock forever.
    """
    env = _env()
    if statement_timeout_ms is not None:
        env["PGOPTIONS"] = f"-c statement_timeout={statement_timeout_ms}"
    return _run(
        [
            binary(spec, "psql"),
            "-h",
            str(spec.sock_dir),
            "-U",
            spec.superuser,
            "-d",
            dbname,
            "-Atc",
            sql,
        ],
        env=env,
    )


def is_ready(spec: ClusterSpec) -> bool:
    if not spec.data_dir.exists():
        return False
    res = _run(
        [
            binary(spec, "pg_isready"),
            "-h",
            str(spec.sock_dir),
            "-U",
            spec.superuser,
        ]
    )
    return res.returncode == 0


def log_tail(spec: ClusterSpec, max_lines: int = 80) -> str:
    if not spec.log_file.exists():
        return ""
    lines = spec.log_file.read_text(errors="replace").splitlines()
    return "\n".join(lines[-max_lines:]) + "\n"


def initdb_if_needed(spec: ClusterSpec) -> int:
    """Initialize the data directory once; recover a partial init."""
    data_dir = spec.data_dir
    if (data_dir / "PG_VERSION").exists():
        return 0
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
    res = _run(
        [
            binary(spec, "initdb"),
            "-D",
            str(data_dir),
            "-U",
            spec.superuser,
            "--auth=trust",
            "--locale=C",
            "--encoding=UTF8",
        ]
    )
    if res.returncode != 0:
        sys.stderr.write(res.stdout + res.stderr)
    return res.returncode


def data_dir_major_mismatch(spec: ClusterSpec) -> Optional[str]:
    """Name an initialized data directory the spec's server cannot open.

    Returns ``"data directory PG N, server PG M"`` when the major versions
    differ, else ``None`` (uninitialized, unreadable, or matching).
    """
    marker = spec.data_dir / "PG_VERSION"
    if not marker.is_file():
        return None
    data_major = marker.read_text(errors="replace").strip()
    try:
        res = _run([binary(spec, "pg_ctl"), "--version"])
    except FileNotFoundError:
        return None
    words = (res.stdout or "").split()
    server_major = words[-1].split(".")[0] if res.returncode == 0 and words else ""
    if not server_major or server_major == data_major:
        return None
    return f"data directory PG {data_major}, server PG {server_major}"


def server_options(spec: ClusterSpec) -> str:
    """The ``pg_ctl -o`` option string: socket-only plus spec settings."""
    parts = [
        f"-k {spec.sock_dir}",
        f"-p {SOCKET_PORT}",
        "-c listen_addresses=''",
    ]
    parts.extend(f"-c {name}={value}" for name, value in spec.server_settings)
    return " ".join(parts)


def start_server(spec: ClusterSpec) -> subprocess.CompletedProcess:
    return _run(
        [
            binary(spec, "pg_ctl"),
            "-D",
            str(spec.data_dir),
            "-l",
            str(spec.log_file),
            "-o",
            server_options(spec),
            "-w",
            "start",
        ]
    )


def ensure_started(spec: ClusterSpec) -> int:
    """Idempotently bring the cluster up: initdb if new, start if down."""
    _ensure_private_socket_dir(spec.sock_dir)
    rc = initdb_if_needed(spec)
    if rc != 0:
        return rc
    if not is_ready(spec):
        res = start_server(spec)
        if res.returncode != 0:
            sys.stderr.write(res.stdout + res.stderr)
            sys.stderr.write(log_tail(spec))
            return res.returncode
    return 0


def _ensure_private_socket_dir(path: Path) -> None:
    """Create and validate the trust-auth socket directory without symlinks."""
    try:
        create_private_directory(path)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except OSError as exc:
        raise PostgresClusterError(
            f"Postgres socket path is not a private directory: {path}"
        ) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode):
            raise PostgresClusterError(
                f"Postgres socket path is not a directory: {path}"
            )
        getuid = getattr(os, "getuid", None)
        if getuid is not None and info.st_uid != getuid():
            raise PostgresClusterError(
                f"Postgres socket directory is not owned by this user: {path}"
            )
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def stop(spec: ClusterSpec) -> int:
    """Stop the server (keep the data directory). No-op when absent/down."""
    if not spec.data_dir.exists():
        return 0
    res = _run(
        [
            binary(spec, "pg_ctl"),
            "-D",
            str(spec.data_dir),
            "-m",
            spec.stop_mode,
            "stop",
        ]
    )
    return 0 if res.returncode == 0 or not is_ready(spec) else res.returncode


def destroy(spec: ClusterSpec) -> int:
    """Stop the server and remove the whole cluster root."""
    stop(spec)
    if spec.root.exists():
        shutil.rmtree(spec.root, ignore_errors=True)
    if spec.socket_dir is not None:
        try:
            spec.socket_dir.rmdir()
        except OSError:
            pass
    return 0


__all__ = [
    "ClusterSpec",
    "PostgresClusterError",
    "SOCKET_PORT",
    "binary",
    "data_dir_major_mismatch",
    "destroy",
    "dsn",
    "ensure_started",
    "executable",
    "initdb_if_needed",
    "is_ready",
    "log_tail",
    "psql",
    "server_options",
    "socket_dir_for_root",
    "start_server",
    "stop",
]

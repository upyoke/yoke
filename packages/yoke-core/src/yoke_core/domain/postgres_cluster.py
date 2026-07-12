"""Shared initdb/pg_ctl choreography for Yoke-managed Postgres clusters.

One cluster-lifecycle core, two frontends:

* :mod:`yoke_core.tools.pg_testcluster` — the disposable test cluster
  (system binaries, scratch root, durability turned off).
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

import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

#: The in-socket-directory port suffix Postgres uses to name the socket
#: file (``.s.PGSQL.<port>``). With ``listen_addresses=''`` no TCP socket
#: is bound, so this never collides with another server: each managed
#: cluster owns a private socket directory.
SOCKET_PORT = 5432


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


def executable(bin_dir: Optional[Path], name: str) -> str:
    """Resolve one Postgres executable from an optional pinned bin dir.

    ``None`` falls back to ``PATH`` (bare name); a directory pins the
    tool. One resolution rule shared by the cluster lifecycle (via
    :func:`binary`) and standalone tool invocations such as the
    universe-export ``pg_dump``.
    """
    if bin_dir is None:
        return name
    return str(bin_dir / name)


def binary(spec: ClusterSpec, name: str) -> str:
    """Resolve one Postgres executable per the spec's binary source."""
    return executable(spec.bin_dir, name)


def _env() -> dict:
    # LC_ALL=C avoids the macOS "postmaster became multithreaded during
    # startup" FATAL that fires when the cluster inherits an unset/invalid
    # locale.
    return {**os.environ, "LC_ALL": "C", "LANG": "C"}


def _run(argv, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=_env(), text=True, capture_output=True, **kw)


def dsn(spec: ClusterSpec, dbname: str = "postgres") -> str:
    """Key/value DSN for the cluster over its unix socket."""
    return f"host={spec.sock_dir} user={spec.superuser} dbname={dbname}"


def psql(
    spec: ClusterSpec, sql: str, dbname: str = "postgres"
) -> subprocess.CompletedProcess:
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
        ]
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
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
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
    "destroy",
    "dsn",
    "ensure_started",
    "executable",
    "initdb_if_needed",
    "is_ready",
    "log_tail",
    "psql",
    "server_options",
    "start_server",
    "stop",
]

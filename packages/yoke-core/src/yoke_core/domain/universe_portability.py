"""Portable universe archive validation, dump, restore, and compatibility.

The artifact is the custom-format ``pg_dump`` file produced by
``yoke universe export``.  Hosted and self-host front doors use this module
at the DSN enforcement point; clients never receive or submit a database
credential.

An upload is never restored over a live universe.  Callers restore into a
fresh database, converge the current additive schema there, and compare its
schema fingerprint with the known-good empty target before switching any
registry pointer.  This module owns the reusable, mode-neutral pieces of that
flow.  The platform owns the registry/runtime cutover and its rollback.
"""

from __future__ import annotations

import os
import re
import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping, Optional, Sequence

from psycopg import conninfo, pq

from yoke_core.domain import postgres_binaries, postgres_cluster


_log = logging.getLogger("yoke.universe.portability")


ARCHIVE_FORMAT = "pg_dump-custom"
ARCHIVE_MAGIC = b"PGDMP"
DEFAULT_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
DEFAULT_ARCHIVE_TIMEOUT_S = 600
DEFAULT_MAX_RESTORE_EXPANSION = 16

# pg_dump 17 adds this session setting even when it dumps an older server;
# PostgreSQL 16 rejects it.  The restore pipeline removes only this exact
# preamble command, before the first archive object, so a local PG17 universe
# remains portable to a hosted PG16 cluster without rewriting any user data.
_COMPATIBILITY_PREAMBLE_LINES = frozenset({
    b"SET transaction_timeout = 0;\n",
})
_PREAMBLE_LINE_LIMIT = 256
_PUMP_CHUNK_BYTES = 1 << 20
_DIAGNOSTIC_BYTES = 32 * 1024

# A portable universe carries ordinary public-schema objects only.  These
# cluster/global object kinds are never required by Yoke and would widen an
# importing tenant owner's authority surface for no product benefit.
_REFUSED_TOC_KINDS = (
    " DATABASE ",
    " EXTENSION ",
    " FOREIGN DATA WRAPPER ",
    " FOREIGN SERVER ",
    " PROCEDURAL LANGUAGE ",
    " PUBLICATION ",
    " SUBSCRIPTION ",
    " USER MAPPING ",
)
_DUMPED_FROM_RE = re.compile(r"^;\s+Dumped from database version:\s+(.+)$", re.M)
_DUMPED_BY_RE = re.compile(r"^;\s+Dumped by pg_dump version:\s+(.+)$", re.M)

# A freshly born universe has identity, role, permission, and bootstrap event
# rows.  These tables represent user-created work; any row makes the hosted
# target non-empty and therefore ineligible for overwrite.
USER_CONTENT_TABLES: tuple[str, ...] = (
    "projects",
    "items",
    "strategy_docs",
    "deployment_runs",
    "harness_sessions",
    "epic_tasks",
)


class UniversePortabilityError(RuntimeError):
    """A portable archive operation was refused or failed safely."""


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


def _postgres_executable(name: str) -> str:
    return postgres_cluster.executable(
        postgres_binaries.installed_bin_dir(), name,
    )


def _subprocess_base_env() -> dict[str, str]:
    """Small non-secret base for postgres client subprocesses."""
    allowed = (
        "HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMROOT",
        "TMP", "TMPDIR", "TEMP",
    )
    return {key: os.environ[key] for key in allowed if key in os.environ}


def postgres_client_env(
    dsn: str,
    *,
    base: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Translate a libpq DSN into ``PG*`` env without putting it in argv.

    ``ps`` therefore shows only ``pg_dump``/``pg_restore`` flags and archive
    paths.  libpq's own option catalog supplies the authoritative keyword to
    environment-variable mapping, including SSL options; no credential or CA
    setting is silently dropped by a hand-maintained subset.
    """
    parsed = conninfo.conninfo_to_dict(dsn)
    env: MutableMapping[str, str] = dict(
        _subprocess_base_env() if base is None else base
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


def inspect_archive(
    path: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
) -> ArchiveInspection:
    """Validate size, magic, listability, and the safe TOC object boundary."""
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
    executable = pg_restore or _postgres_executable("pg_restore")
    try:
        listed = subprocess.run(
            [executable, "--list", str(archive)],
            env=_subprocess_base_env(),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail = "timed out" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        raise ArchiveInvalidError(
            f"the universe archive could not be inspected: {detail}"
        ) from exc
    if listed.returncode != 0:
        detail = (listed.stderr or "").strip().splitlines()[-1:]
        raise ArchiveInvalidError(
            "the universe archive catalog is corrupt or unreadable"
            + (f": {detail[0]}" if detail else "")
        )
    catalog = listed.stdout
    toc_lines = [line for line in catalog.splitlines() if not line.startswith(";")]
    upper_toc = "\n".join(toc_lines).upper()
    refused = [kind.strip() for kind in _REFUSED_TOC_KINDS if kind in upper_toc]
    if refused:
        raise ArchiveInvalidError(
            "the universe archive contains cluster/global object kinds that"
            f" are not portable: {', '.join(sorted(set(refused)))}"
        )
    # pg_restore list rows are semicolon-prefixed IDs; TABLE and TABLE DATA
    # entries prove this is a database archive rather than an empty catalog.
    table_entries = sum(
        1 for line in catalog.splitlines()
        if not line.startswith(";") and (" TABLE " in line or " TABLE DATA " in line)
    )
    if table_entries == 0 or " organizations " not in catalog.lower():
        raise ArchiveInvalidError(
            "the archive contains no Yoke organization table"
        )
    dumped_from = _DUMPED_FROM_RE.search(catalog)
    dumped_by = _DUMPED_BY_RE.search(catalog)
    if dumped_from is None or dumped_by is None:
        raise ArchiveInvalidError(
            "the archive catalog omits its PostgreSQL version headers"
        )
    return ArchiveInspection(
        path=archive,
        size_bytes=size,
        dumped_from_postgres=dumped_from.group(1).strip(),
        dumped_by_pg_dump=dumped_by.group(1).strip(),
        table_entries=table_entries,
    )


def dump_universe(
    dsn: str,
    destination: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_dump: Optional[str] = None,
) -> ArchiveInspection:
    """Create and inspect one portable dump, deleting every failed artifact."""
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    executable = pg_dump or _postgres_executable("pg_dump")
    client_env = postgres_client_env(dsn)
    stderr_tail = bytearray()
    pump_errors: list[BaseException] = []
    try:
        process = subprocess.Popen(
            [
                executable,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
            ],
            env=client_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise UniversePortabilityError(f"universe export could not start: {exc}") from exc
    assert process.stdout is not None and process.stderr is not None
    workers = (
        threading.Thread(
            target=_archive_pump,
            args=(process.stdout, dest),
            kwargs={"max_bytes": max_bytes, "errors": pump_errors},
            daemon=True,
        ),
        threading.Thread(
            target=_bounded_diagnostic_reader,
            args=(process.stderr, stderr_tail),
            daemon=True,
        ),
    )
    for worker in workers:
        worker.start()
    try:
        process.wait(timeout=timeout_s)
        workers[0].join(timeout=5)
        if workers[0].is_alive():
            raise subprocess.TimeoutExpired([executable], timeout_s)
    except subprocess.TimeoutExpired as exc:
        _terminate(process)
        dest.unlink(missing_ok=True)
        raise UniversePortabilityError(
            f"universe export timed out after {timeout_s}s"
        ) from exc
    finally:
        _terminate(process)
        for worker in workers:
            worker.join(timeout=5)
    if pump_errors:
        dest.unlink(missing_ok=True)
        error = pump_errors[0]
        if isinstance(error, ArchiveTooLargeError):
            raise error
        raise UniversePortabilityError(
            "universe export stream failed before the archive completed"
        ) from error
    if process.returncode != 0:
        dest.unlink(missing_ok=True)
        diagnostic = bytes(stderr_tail).decode("utf-8", errors="replace")
        password = client_env.get("PGPASSWORD", "")
        if password:
            diagnostic = diagnostic.replace(password, "<redacted-secret>")
        _log.error(
            "portable universe export failed rc=%s; redacted stderr tail:\n%s",
            process.returncode,
            "\n".join(diagnostic.strip().splitlines()[-12:]) or "<no stderr>",
        )
        raise UniversePortabilityError(
            "universe export failed; see the server log for the redacted"
            " pg_dump diagnostic"
        )
    try:
        return inspect_archive(
            dest, max_bytes=max_bytes, timeout_s=timeout_s,
        )
    except UniversePortabilityError:
        dest.unlink(missing_ok=True)
        raise


def _archive_pump(
    source: object,
    destination: Path,
    *,
    max_bytes: int,
    errors: list[BaseException],
) -> None:
    """Write pg_dump stdout to a private file with an in-flight hard ceiling."""
    written = 0
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            while True:
                chunk = source.read(_PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ArchiveTooLargeError(
                        "the universe archive exceeds the"
                        f" {max_bytes}-byte safety limit"
                    )
                output.write(chunk)
    except BaseException as exc:  # noqa: BLE001 - crosses a worker thread
        errors.append(exc)
    finally:
        source.close()  # type: ignore[attr-defined]


def restore_universe(
    archive: Path | str,
    dsn: str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
) -> ArchiveInspection:
    """Restore a validated archive into a fresh DB in one transaction.

    ``--schema=public`` and the refused TOC-kind inspection keep an uploaded
    archive inside the tenant schema.  The caller must supply a fresh database;
    no clean/drop flags exist here, making accidental overwrite impossible.
    """
    inspection = inspect_archive(
        archive, max_bytes=max_bytes, timeout_s=timeout_s,
        pg_restore=pg_restore,
    )
    executable = pg_restore or _postgres_executable("pg_restore")
    psql = _postgres_executable("psql")
    dbname = conninfo.conninfo_to_dict(dsn).get("dbname")
    if not dbname:
        raise UniversePortabilityError(
            "the restore target DSN must name a database"
        )
    client_env = postgres_client_env(dsn)
    _restore_via_filtered_sql(
        executable=executable,
        psql=psql,
        archive=inspection.path,
        dbname=str(dbname),
        client_env=client_env,
        timeout_s=timeout_s,
        max_sql_bytes=max(
            64 * 1024 * 1024,
            max_bytes * DEFAULT_MAX_RESTORE_EXPANSION,
        ),
    )
    return inspection


def _bounded_diagnostic_reader(stream: object, sink: bytearray) -> None:
    """Drain a subprocess stderr pipe while retaining only its bounded tail."""
    try:
        while True:
            chunk = stream.read(_PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
            if not chunk:
                return
            sink.extend(chunk)
            if len(sink) > _DIAGNOSTIC_BYTES:
                del sink[:-_DIAGNOSTIC_BYTES]
    finally:
        stream.close()  # type: ignore[attr-defined]


def _sql_pump(
    source: object,
    destination: object,
    *,
    max_sql_bytes: int,
    errors: list[BaseException],
) -> None:
    """Stream pg_restore SQL to psql, filtering only known preamble lines."""
    written = 0

    def write(chunk: bytes) -> None:
        nonlocal written
        if not chunk:
            return
        written += len(chunk)
        if written > max_sql_bytes:
            raise ArchiveTooLargeError(
                "the expanded universe restore exceeds the"
                f" {max_sql_bytes}-byte safety limit"
            )
        destination.write(chunk)  # type: ignore[attr-defined]

    try:
        write(b"BEGIN;\n")
        # Compatibility settings live in pg_restore's short preamble.  Stop
        # line parsing at the first object marker, then stream raw fixed-size
        # chunks so an attacker cannot force an unbounded readline allocation
        # with one enormous COPY field.
        for _index in range(_PREAMBLE_LINE_LIMIT):
            line = source.readline(64 * 1024)  # type: ignore[attr-defined]
            if not line:
                break
            if line not in _COMPATIBILITY_PREAMBLE_LINES:
                write(line)
            if line.startswith(b"-- Name:"):
                break
        while True:
            chunk = source.read(_PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
            if not chunk:
                break
            write(chunk)
    except BaseException as exc:  # noqa: BLE001 - crosses a worker thread
        errors.append(exc)
    finally:
        source.close()  # type: ignore[attr-defined]


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _restore_via_filtered_sql(
    *,
    executable: str,
    psql: str,
    archive: Path,
    dbname: str,
    client_env: Mapping[str, str],
    timeout_s: int,
    max_sql_bytes: int,
) -> None:
    """Generate filtered SQL and execute it as one fail-closed transaction."""
    restore_cmd = [
        executable,
        "--file=-",
        "--no-owner",
        "--no-privileges",
        "--no-comments",
        "--no-publications",
        "--no-security-labels",
        "--no-subscriptions",
        "--schema=public",
        str(archive),
    ]
    psql_cmd = [
        psql,
        "--dbname", dbname,
        "--no-psqlrc",
        "--set=ON_ERROR_STOP=1",
    ]
    restore: subprocess.Popen[bytes] | None = None
    apply: subprocess.Popen[bytes] | None = None
    try:
        restore = subprocess.Popen(
            restore_cmd,
            env=dict(client_env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        apply = subprocess.Popen(
            psql_cmd,
            env=dict(client_env),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        if restore is not None:
            _terminate(restore)
        raise UniversePortabilityError(
            f"universe restore client could not start: {exc}"
        ) from exc
    assert restore is not None and apply is not None
    assert restore.stdout is not None and restore.stderr is not None
    assert apply.stdin is not None and apply.stderr is not None
    pump_errors: list[BaseException] = []
    restore_stderr = bytearray()
    apply_stderr = bytearray()
    workers = (
        threading.Thread(
            target=_sql_pump,
            args=(restore.stdout, apply.stdin),
            kwargs={"max_sql_bytes": max_sql_bytes, "errors": pump_errors},
            daemon=True,
        ),
        threading.Thread(
            target=_bounded_diagnostic_reader,
            args=(restore.stderr, restore_stderr),
            daemon=True,
        ),
        threading.Thread(
            target=_bounded_diagnostic_reader,
            args=(apply.stderr, apply_stderr),
            daemon=True,
        ),
    )
    for worker in workers:
        worker.start()
    deadline = time.monotonic() + timeout_s
    try:
        restore.wait(timeout=max(0.001, deadline - time.monotonic()))
        workers[0].join(timeout=max(0.001, deadline - time.monotonic()))
        if workers[0].is_alive():
            raise subprocess.TimeoutExpired(restore_cmd, timeout_s)
        # The generator must finish cleanly before COMMIT ever reaches psql.
        # Closing an uncommitted stream rolls back, so corrupt/oversized input
        # cannot leave even partial state in the fresh staging database.
        try:
            if restore.returncode == 0 and not pump_errors:
                apply.stdin.write(b"COMMIT;\n")
            else:
                apply.stdin.write(b"ROLLBACK;\n")
        except BrokenPipeError:
            pass
        finally:
            try:
                apply.stdin.close()
            except BrokenPipeError:
                pass
        apply.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as exc:
        _terminate(restore)
        _terminate(apply)
        raise UniversePortabilityError(
            f"universe restore timed out after {timeout_s}s"
        ) from exc
    finally:
        _terminate(restore)
        _terminate(apply)
        for worker in workers:
            worker.join(timeout=5)
    if pump_errors:
        error = pump_errors[0]
        if isinstance(error, ArchiveTooLargeError):
            raise error
        if apply.returncode == 0:
            raise UniversePortabilityError(
                "universe restore stream failed before the transaction completed"
            ) from error
    if restore.returncode != 0 or apply.returncode != 0:
        diagnostic = bytes(restore_stderr + apply_stderr).decode(
            "utf-8", errors="replace",
        )
        password = client_env.get("PGPASSWORD", "")
        if password:
            diagnostic = diagnostic.replace(password, "<redacted-secret>")
        diagnostic = "\n".join(diagnostic.strip().splitlines()[-12:])
        _log.error(
            "portable universe restore failed generator_rc=%s apply_rc=%s;"
            " redacted stderr tail:\n%s",
            restore.returncode,
            apply.returncode,
            diagnostic or "<no stderr>",
        )
        raise UniversePortabilityError(
            "universe restore failed transactionally; the staging database"
            " was not accepted"
        )


def user_content_counts(
    conn: object,
    tables: Sequence[str] = USER_CONTENT_TABLES,
) -> dict[str, int]:
    """Return user-created row counts, treating an absent table as incompatible."""
    present_rows = conn.execute(  # type: ignore[attr-defined]
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        (list(tables),),
    ).fetchall()
    present = {str(row[0]) for row in present_rows}
    missing = sorted(set(tables).difference(present))
    if missing:
        raise ArchiveCompatibilityError(
            "the universe schema is missing content tables: " + ", ".join(missing)
        )
    counts: dict[str, int] = {}
    for table in tables:
        # Names come only from the module constant/caller-owned trusted tuple,
        # never from an archive or request.
        row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()  # type: ignore[attr-defined]
        counts[table] = int(row[0])
    return counts


def converge_and_validate_restored_universe(
    dsn: str,
    *,
    expected_org_slug: str,
    expected_schema_fingerprint: str,
) -> dict[str, object]:
    """Converge an imported DB and prove org identity + exact current schema."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.actor_permissions import seed_roles_and_permissions
    from yoke_core.domain.schema_fingerprint import fingerprint_kind
    from yoke_core.domain.schema_init import converge_core_schema
    from yoke_core.domain.schema_readiness import missing_readiness_tables

    conn = db_backend.connect_psycopg(dsn)
    try:
        # Some legacy convergence steps own explicit commits, so they cannot
        # run inside psycopg's nested ``transaction()`` context.  The database
        # is isolated staging authority at this point; the archive restore was
        # already atomic, and callers drop staging on any validation failure.
        converge_core_schema(conn)
        seed_roles_and_permissions(conn)
        conn.commit()
        organizations = conn.execute(
            "SELECT slug FROM organizations ORDER BY id"
        ).fetchall()
        if len(organizations) != 1:
            raise ArchiveCompatibilityError(
                "a portable universe must contain exactly one organization"
            )
        actual_slug = str(organizations[0][0])
        if actual_slug != expected_org_slug:
            raise ArchiveCompatibilityError(
                f"archive organization {actual_slug!r} does not match hosted"
                f" organization {expected_org_slug!r}"
            )
        missing = missing_readiness_tables(conn)
        if missing:
            raise ArchiveCompatibilityError(
                "the restored universe is missing required tables after"
                " convergence: " + ", ".join(missing)
            )
        actual_fingerprint = fingerprint_kind("postgres", conn)
        if actual_fingerprint != expected_schema_fingerprint:
            raise ArchiveCompatibilityError(
                "the restored universe schema is not compatible with the"
                " deployed engine release"
            )
        counts = user_content_counts(conn)
    finally:
        conn.close()
    return {
        "org": expected_org_slug,
        "schema_fingerprint": expected_schema_fingerprint,
        "content_counts": counts,
    }


__all__ = [
    "ARCHIVE_FORMAT",
    "ARCHIVE_MAGIC",
    "DEFAULT_ARCHIVE_TIMEOUT_S",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "ArchiveCompatibilityError",
    "ArchiveInspection",
    "ArchiveInvalidError",
    "ArchiveTooLargeError",
    "UniversePortabilityError",
    "USER_CONTENT_TABLES",
    "converge_and_validate_restored_universe",
    "dump_universe",
    "inspect_archive",
    "postgres_client_env",
    "restore_universe",
    "user_content_counts",
]

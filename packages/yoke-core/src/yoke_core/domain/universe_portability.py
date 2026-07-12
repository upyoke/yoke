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
import tempfile
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
_CATALOG_BYTES = 16 * 1024 * 1024

# Only inert relational structure/data is replayed from an uploaded archive.
# Executable or authority-bearing entries are recognized so they can be
# deliberately omitted from the pg_restore use-list; an unknown descriptor is
# rejected instead of silently becoming executable when PostgreSQL adds one.
_RESTORED_TOC_KINDS = (
    "SEQUENCE OWNED BY",
    "SEQUENCE SET",
    "TABLE ATTACH",
    "TABLE DATA",
    "FK CONSTRAINT",
    "CHECK CONSTRAINT",
    "INDEX ATTACH",
    "CONSTRAINT",
    "SEQUENCE",
    "DEFAULT",
    "INDEX",
    "TABLE",
)
_OMITTED_TOC_KINDS = (
    "TEXT SEARCH CONFIGURATION",
    "TEXT SEARCH DICTIONARY",
    "TEXT SEARCH PARSER",
    "TEXT SEARCH TEMPLATE",
    "FOREIGN DATA WRAPPER",
    "MATERIALIZED VIEW DATA",
    "PROCEDURAL LANGUAGE",
    "PUBLICATION TABLE",
    "DEFAULT ACL",
    "DOMAIN CONSTRAINT",
    "EVENT TRIGGER",
    "FOREIGN SERVER",
    "FOREIGN TABLE",
    "MATERIALIZED VIEW",
    "OPERATOR CLASS",
    "OPERATOR FAMILY",
    "SECURITY LABEL",
    "USER MAPPING",
    "AGGREGATE",
    "BLOB COMMENTS",
    "COLLATION",
    "CONVERSION",
    "DATABASE",
    "EXTENSION",
    "FUNCTION",
    "OPERATOR",
    "POLICY",
    "PROCEDURE",
    "PUBLICATION",
    "ROW SECURITY",
    "STATISTICS",
    "SUBSCRIPTION",
    "TRANSFORM",
    "TRIGGER",
    "TYPE",
    "BLOB",
    "CAST",
    "COMMENT",
    "DOMAIN",
    "PROCACT_SCHEMA",
    "RULE",
    "SCHEMA",
    "VIEW",
    "ACL",
)
_TOC_KINDS = tuple(
    sorted(
        set(_RESTORED_TOC_KINDS + _OMITTED_TOC_KINDS),
        key=lambda value: (-len(value), value),
    )
)
_TOC_ROW_RE = re.compile(r"^\d+;\s+\d+\s+\d+\s+(.+)$")
_DUMPED_FROM_RE = re.compile(r"^;\s+Dumped from database version:\s+(.+)$", re.M)
_DUMPED_BY_RE = re.compile(r"^;\s+Dumped by pg_dump version:\s+(.+)$", re.M)

# A freshly born universe has identity, role, permission, and bootstrap event
# rows.  These tables represent user-created work; any row makes the hosted
# target non-empty and therefore ineligible for overwrite.
USER_CONTENT_TABLES: tuple[str, ...] = (
    "actor_invites",
    "actor_project_roles",
    "capability_secrets",
    "caveat_dispositions",
    "coordination_leases",
    "deployment_run_items",
    "deployment_run_qa",
    "projects",
    "items",
    "item_activity_days",
    "item_dependencies",
    "item_sections",
    "item_status_transitions",
    "designs",
    "epic_dispatch_chains",
    "epic_progress_notes",
    "epic_task_files",
    "epic_tasks",
    "release_entries",
    "qa_artifacts",
    "qa_requirements",
    "qa_runs",
    "strategy_docs",
    "strategy_checkpoints",
    "strategize_landed_carry",
    "deployment_runs",
    "ephemeral_environments",
    "environments",
    "events",
    "function_call_ledger",
    "github_app_installations",
    "github_workflow_dispatch_intents",
    "harness_sessions",
    "merge_locks",
    "migration_audit",
    "ouroboros_entries",
    "path_claim_amendments",
    "path_claim_overrides",
    "path_claim_targets",
    "path_claims",
    "path_context_values",
    "path_integrity_failures",
    "path_integrity_fixtures",
    "path_integrity_repairs",
    "path_integrity_runs",
    "path_moves",
    "path_snapshot_entries",
    "path_snapshot_symlink_facts",
    "path_snapshot_sync_upload_chunks",
    "path_snapshot_sync_uploads",
    "path_snapshots",
    "path_targets",
    "project_capabilities",
    "project_github_repo_bindings",
    "session_tool_calls",
    "shepherd_verdicts",
    "sites",
    "web_sessions",
    "work_claims",
    "wrapup_reports",
)
_USER_CONTENT_COUNT_SQL = {
    # Hosted birth admits the sole founding admin through the normal invite
    # ladder, leaving exactly one accepted receipt. Pending/revoked invites or
    # any additional accepted identity are user-created work.
    "actor_invites": (
        "SELECT COUNT(*) FILTER (WHERE status <> 'accepted') + "
        "GREATEST(COUNT(*) FILTER (WHERE status = 'accepted') - 1, 0) "
        "FROM actor_invites"
    ),
}


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


def _remaining_timeout(deadline: float, operation: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UniversePortabilityError(
            f"universe {operation} exhausted its end-to-end timeout"
        )
    return max(0.001, remaining)


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


def _catalog_reader(
    stream: object,
    sink: bytearray,
    errors: list[BaseException],
) -> None:
    """Drain one catalog with a hard memory ceiling."""
    try:
        while True:
            chunk = stream.read(_PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
            if not chunk:
                return
            if len(sink) + len(chunk) > _CATALOG_BYTES:
                raise ArchiveInvalidError(
                    "the universe archive catalog exceeds the inspection limit"
                )
            sink.extend(chunk)
    except BaseException as exc:  # noqa: BLE001 - crosses a worker thread
        errors.append(exc)
    finally:
        stream.close()  # type: ignore[attr-defined]


def _archive_catalog(
    archive: Path,
    *,
    executable: str,
    timeout_s: int,
) -> str:
    """Return bounded pg_restore catalog text without buffering its stderr."""
    try:
        process = subprocess.Popen(
            [executable, "--list", str(archive)],
            env=_subprocess_base_env(),
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
            target=_catalog_reader,
            args=(process.stdout, catalog_bytes, errors),
            daemon=True,
        ),
        threading.Thread(
            target=_bounded_diagnostic_reader,
            args=(process.stderr, diagnostic),
            daemon=True,
        ),
    )
    for worker in workers:
        worker.start()
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _terminate(process)
        raise ArchiveInvalidError(
            "the universe archive could not be inspected: timed out"
        ) from exc
    finally:
        _terminate(process)
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


def _toc_kind_and_namespace(line: str) -> tuple[str, str]:
    match = _TOC_ROW_RE.fullmatch(line)
    if match is None:
        raise ArchiveInvalidError(
            "the universe archive contains an unrecognized catalog row"
        )
    remainder = match.group(1)
    for kind in _TOC_KINDS:
        prefix = kind + " "
        if not remainder.startswith(prefix):
            continue
        tail = remainder[len(prefix):]
        namespace = tail.split(" ", 1)[0]
        if kind == "SCHEMA":
            parts = tail.split(" ", 2)
            if len(parts) < 2 or parts[0] != "-" or parts[1] != "public":
                raise ArchiveInvalidError(
                    "the universe archive contains SCHEMA outside public schema"
                )
            return kind, "public"
        if namespace != "public":
            raise ArchiveInvalidError(
                f"the universe archive contains {kind} outside public schema"
            )
        return kind, namespace
    raise ArchiveInvalidError(
        "the universe archive contains an unsupported catalog object kind"
    )


def _validate_catalog(catalog: str) -> int:
    table_entries = 0
    has_org_table = False
    for line in catalog.splitlines():
        if not line or line.startswith(";"):
            continue
        kind, _namespace = _toc_kind_and_namespace(line)
        if kind in ("TABLE", "TABLE DATA"):
            table_entries += 1
        if kind == "TABLE" and " TABLE public organizations " in line:
            has_org_table = True
    if table_entries == 0 or not has_org_table:
        raise ArchiveInvalidError(
            "the archive contains no Yoke organization table"
        )
    return table_entries


def _inspect_archive(
    path: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
) -> tuple[ArchiveInspection, str]:
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
    catalog = _archive_catalog(
        archive, executable=executable, timeout_s=timeout_s,
    )
    table_entries = _validate_catalog(catalog)
    dumped_from = _DUMPED_FROM_RE.search(catalog)
    dumped_by = _DUMPED_BY_RE.search(catalog)
    if dumped_from is None or dumped_by is None:
        raise ArchiveInvalidError(
            "the archive catalog omits its PostgreSQL version headers"
        )
    inspection = ArchiveInspection(
        path=archive,
        size_bytes=size,
        dumped_from_postgres=dumped_from.group(1).strip(),
        dumped_by_pg_dump=dumped_by.group(1).strip(),
        table_entries=table_entries,
    )
    return inspection, catalog


def inspect_archive(
    path: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
) -> ArchiveInspection:
    """Validate size, bounded catalog, versions, schema, and TOC kinds."""
    inspection, _catalog = _inspect_archive(
        path,
        max_bytes=max_bytes,
        timeout_s=timeout_s,
        pg_restore=pg_restore,
    )
    return inspection


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
    deadline = time.monotonic() + timeout_s
    stderr_tail = bytearray()
    pump_errors: list[BaseException] = []
    try:
        process = subprocess.Popen(
            [
                executable,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--no-comments",
                "--no-security-labels",
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
        process.wait(timeout=_remaining_timeout(deadline, "export"))
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
            dest,
            max_bytes=max_bytes,
            timeout_s=_remaining_timeout(deadline, "export"),
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
    deadline = time.monotonic() + timeout_s
    inspection, catalog = _inspect_archive(
        archive,
        max_bytes=max_bytes,
        timeout_s=_remaining_timeout(deadline, "restore"),
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
    restore_list = _write_restore_list(catalog)
    try:
        _restore_via_filtered_sql(
            executable=executable,
            psql=psql,
            archive=inspection.path,
            restore_list=restore_list,
            dbname=str(dbname),
            client_env=client_env,
            timeout_s=_remaining_timeout(deadline, "restore"),
            max_sql_bytes=max(
                64 * 1024 * 1024,
                max_bytes * DEFAULT_MAX_RESTORE_EXPANSION,
            ),
        )
    finally:
        restore_list.unlink(missing_ok=True)
    return inspection


def _write_restore_list(catalog: str) -> Path:
    """Write a private pg_restore list containing only inert public objects."""
    descriptor, raw_path = tempfile.mkstemp(prefix="yoke-universe-", suffix=".toc")
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for line in catalog.splitlines():
                if not line or line.startswith(";"):
                    stream.write(line + "\n")
                    continue
                kind, _namespace = _toc_kind_and_namespace(line)
                if kind in _RESTORED_TOC_KINDS:
                    stream.write(line + "\n")
                else:
                    # pg_restore list files use a leading semicolon to disable
                    # an entry while retaining dependency ordering for the
                    # remaining inert relation/data rows.
                    stream.write(";" + line + "\n")
        path.chmod(0o600)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


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
    restore_list: Path,
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
        "--use-list", str(restore_list),
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
    """Return counts for every known user-work table present in this release.

    Additive releases may introduce a table before an older universe has
    converged it.  Missing tables therefore count as zero here; the separate
    exact schema-fingerprint gate remains responsible for compatibility.
    """
    present_rows = conn.execute(  # type: ignore[attr-defined]
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        (list(tables),),
    ).fetchall()
    present = {str(row[0]) for row in present_rows}
    counts: dict[str, int] = {}
    for table in tables:
        # Names come only from the module constant/caller-owned trusted tuple,
        # never from an archive or request.
        if table in present:
            sql = _USER_CONTENT_COUNT_SQL.get(
                table, f'SELECT COUNT(*) FROM "{table}"',
            )
            row = conn.execute(sql).fetchone()  # type: ignore[attr-defined]
            counts[table] = int(row[0])
        else:
            counts[table] = 0
    return counts


def converge_and_validate_restored_universe(
    dsn: str,
    *,
    expected_org_slug: str,
    expected_schema_fingerprint: str,
    timeout_s: float = DEFAULT_ARCHIVE_TIMEOUT_S,
) -> dict[str, object]:
    """Converge an imported DB and prove org identity + exact current schema."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.actor_permissions import seed_roles_and_permissions
    from yoke_core.domain.schema_fingerprint import fingerprint_kind
    from yoke_core.domain.flow_init import create_or_replace_item_progress_view
    from yoke_core.domain.schema_migrations import _ensure_qa_runs_verdict_trigger
    from yoke_core.domain.schema_init import converge_core_schema
    from yoke_core.domain.schema_readiness import missing_readiness_tables

    parsed_dsn = conninfo.conninfo_to_dict(dsn)
    prior_options = str(parsed_dsn.get("options") or "").strip()
    bounded_options = (
        f"-c statement_timeout={max(1, int(timeout_s * 1000))}"
        f" -c lock_timeout={max(1, int(timeout_s * 1000))}"
    )
    parsed_dsn["options"] = " ".join(
        value for value in (prior_options, bounded_options) if value
    )
    conn = db_backend.connect_psycopg(conninfo.make_conninfo(**parsed_dsn))
    try:
        # Some legacy convergence steps own explicit commits, so they cannot
        # run inside psycopg's nested ``transaction()`` context.  The database
        # is isolated staging authority at this point; the archive restore was
        # already atomic, and callers drop staging on any validation failure.
        converge_core_schema(conn)
        seed_roles_and_permissions(conn)
        # Views and executable schema are deliberately omitted from uploaded
        # TOCs. Recreate the sole canonical view and QA trigger/function from
        # trusted deployed code before the exact fingerprint check.
        create_or_replace_item_progress_view(conn)
        _ensure_qa_runs_verdict_trigger(conn)
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

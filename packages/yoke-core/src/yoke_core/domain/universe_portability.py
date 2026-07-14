"""Validate, dump, and restore portable universe archives safely."""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, MutableMapping, Optional, Sequence

import psycopg
from psycopg import conninfo, pq, sql

from yoke_core.domain import postgres_binaries, postgres_cluster, universe_archive_output


_log = logging.getLogger("yoke.universe.portability")


ARCHIVE_FORMAT = "pg_dump-custom"
ARCHIVE_MAGIC = b"PGDMP"
DEFAULT_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
DEFAULT_ARCHIVE_TIMEOUT_S = 600
DEFAULT_MAX_RESTORE_EXPANSION = 16

_PUMP_CHUNK_BYTES = 1 << 20
_DIAGNOSTIC_BYTES = 32 * 1024
_CATALOG_BYTES = 16 * 1024 * 1024

_SQL_IDENTIFIER = r'(?:"(?:[^"]|"")*"|[a-z_][a-z0-9_$]*)'
_COPY_HEADER_RE = re.compile(
    rf"^COPY (?P<schema>{_SQL_IDENTIFIER})\."
    rf"(?P<table>{_SQL_IDENTIFIER}) "
    rf"\((?P<columns>{_SQL_IDENTIFIER}(?:, {_SQL_IDENTIFIER})*)\) "
    r"FROM stdin;\r?\n$"
)
_SETVAL_RE = re.compile(
    r"^SELECT pg_catalog\.setval\('public\.([a-z_][a-z0-9_]*)'"
    r"(?:::\w+)?\s*,\s*(-?\d+)\s*,\s*(true|false)\);\r?\n$"
)
_SAFE_RESTORE_OBJECT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_RESTORE_SET_RE = re.compile(
    r"^SET (?:statement_timeout|lock_timeout|"
    r"idle_in_transaction_session_timeout|transaction_timeout|"
    r"client_encoding|standard_conforming_strings|check_function_bodies|"
    r"xmloption|client_min_messages|row_security|default_tablespace|"
    r"default_table_access_method) = [^;\r\n]*;\r?\n$"
)
_RESTORE_RESTRICT_RE = re.compile(r"^\\(?:un)?restrict [^\s\r\n]+\r?\n$")
_RESTORE_SEARCH_PATH = "SELECT pg_catalog.set_config('search_path', '', false);"

# Uploaded archives contribute data only. The target schema is materialized
# from deployed code before pg_restore runs, so even an archive with forged
# allowed-object DDL never supplies executable schema. Unknown descriptors are
# rejected instead of silently becoming restorable when PostgreSQL adds one.
_RESTORED_DATA_TOC_KINDS = (
    "SEQUENCE SET",
    "TABLE DATA",
)
_OMITTED_TOC_KINDS = (
    "SEQUENCE OWNED BY",
    "TABLE ATTACH",
    "FK CONSTRAINT",
    "CHECK CONSTRAINT",
    "INDEX ATTACH",
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
    "CONSTRAINT",
    "SEQUENCE",
    "DEFAULT",
    "INDEX",
    "TABLE",
    "DOMAIN",
    "PROCACT_SCHEMA",
    "RULE",
    "SCHEMA",
    "VIEW",
    "ACL",
)
_TOC_KINDS = tuple(
    sorted(
        set(_RESTORED_DATA_TOC_KINDS + _OMITTED_TOC_KINDS),
        key=lambda value: (-len(value), value),
    )
)
_TOC_ROW_RE = re.compile(r"^\d+;\s+\d+\s+\d+\s+(.+)$")
_DUMPED_FROM_RE = re.compile(r"^;\s+Dumped from database version:\s+(.+)$", re.M)
_DUMPED_BY_RE = re.compile(r"^;\s+Dumped by pg_dump version:\s+(.+)$", re.M)

# Portable archives are data contracts across engine releases.  The current
# trusted schema owns every object and column; this manifest names only
# previously shipped, lossless schema evolutions that the loader may bridge.
# Any unlisted table or column drift remains a compatibility error.
_ARCHIVE_OMITTABLE_TARGET_TABLES = frozenset()
_ARCHIVE_OMITTABLE_TARGET_SEQUENCES = frozenset()
_ARCHIVE_OMITTABLE_TARGET_COLUMNS = {
    "project_github_repo_bindings": frozenset(
        {"last_sync_at", "last_sync_outcome", "last_sync_error"}
    ),
}
_ARCHIVE_COLUMN_RENAMES = {
    ("qa_artifacts", "storage_path"): "artifact_handle",
}

# A freshly born universe has identity, role, permission, and bootstrap event
# rows.  These tables represent user-created work; any row makes the hosted
# target non-empty and therefore ineligible for overwrite.
USER_CONTENT_TABLES: tuple[str, ...] = (
    "actor_invites",
    "actor_project_roles",
    "api_token_audit",
    "api_tokens",
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
    "project_onboarding_checklist_rows",
    "project_onboarding_runs",
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
        postgres_binaries.installed_bin_dir(),
        name,
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
        tail = remainder[len(prefix) :]
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
        raise ArchiveInvalidError("the archive contains no Yoke organization table")
    return table_entries


def _catalog_data_targets(catalog: str) -> tuple[set[str], set[str]]:
    """Return canonical public table/sequence names enabled for data restore."""
    tables: set[str] = set()
    sequences: set[str] = set()
    for line in catalog.splitlines():
        if not line or line.startswith(";"):
            continue
        match = _TOC_ROW_RE.fullmatch(line)
        if match is None:
            raise ArchiveInvalidError(
                "the universe archive contains an unrecognized catalog row"
            )
        remainder = match.group(1)
        for kind, sink in (
            ("TABLE DATA", tables),
            ("SEQUENCE SET", sequences),
        ):
            prefix = f"{kind} public "
            if not remainder.startswith(prefix):
                continue
            object_name = remainder[len(prefix) :].split(" ", 1)[0]
            if _SAFE_RESTORE_OBJECT_RE.fullmatch(object_name) is None:
                raise ArchiveInvalidError(
                    f"the universe archive contains a noncanonical {kind} name"
                )
            sink.add(object_name)
            break
    return tables, sequences


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
        archive,
        executable=executable,
        timeout_s=timeout_s,
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
    try:
        archive_output = universe_archive_output.prepare_private_archive_output(dest)
    except universe_archive_output.PrivateArchiveOutputError as exc:
        raise UniversePortabilityError(str(exc)) from exc
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
        archive_output.cleanup()
        raise UniversePortabilityError(
            f"universe export could not start: {exc}"
        ) from exc
    assert process.stdout is not None and process.stderr is not None
    workers = (
        threading.Thread(
            target=_archive_pump,
            args=(process.stdout, archive_output),
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
        archive_output.cleanup()
        raise UniversePortabilityError(
            f"universe export timed out after {timeout_s}s"
        ) from exc
    finally:
        _terminate(process)
        for worker in workers:
            worker.join(timeout=5)
    if pump_errors:
        archive_output.cleanup()
        error = pump_errors[0]
        if isinstance(error, ArchiveTooLargeError):
            raise error
        raise UniversePortabilityError(
            "universe export stream failed before the archive completed"
        ) from error
    if process.returncode != 0:
        archive_output.cleanup()
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
        inspection = inspect_archive(
            archive_output.temporary,
            max_bytes=max_bytes,
            timeout_s=_remaining_timeout(deadline, "export"),
        )
        archive_output.commit()
        return inspection
    except UniversePortabilityError:
        archive_output.cleanup()
        raise
    except universe_archive_output.PrivateArchiveOutputError as exc:
        archive_output.cleanup()
        raise UniversePortabilityError(str(exc)) from exc


def _archive_pump(
    source: object,
    output: object,
    *,
    max_bytes: int,
    errors: list[BaseException],
) -> None:
    """Write pg_dump stdout to a private file with an in-flight hard ceiling."""
    written = 0
    try:
        with output as stream:
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
                stream.write(chunk)
    except BaseException as exc:  # noqa: BLE001 - crosses a worker thread
        errors.append(exc)
    finally:
        source.close()  # type: ignore[attr-defined]


def _prepare_trusted_restore_schema(dsn: str, *, timeout_s: float) -> None:
    """Require a catalog-empty DB and materialize schema from deployed code."""

    from yoke_core.domain import db_backend
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn

    parsed = conninfo.conninfo_to_dict(dsn)
    prior_options = str(parsed.get("options") or "").strip()
    timeout_ms = max(1, int(timeout_s * 1000))
    bounded_options = (
        f"-c statement_timeout={timeout_ms} -c lock_timeout={timeout_ms}"
        " -c search_path=public,pg_catalog"
    )
    parsed["options"] = " ".join(
        value for value in (prior_options, bounded_options) if value
    )
    parsed["connect_timeout"] = str(max(1, min(30, math.ceil(timeout_s))))
    bounded_dsn = conninfo.make_conninfo(**parsed)
    conn = db_backend.connect_psycopg(bounded_dsn)
    try:
        existing = conn.execute(
            "SELECT object_name FROM ("
            " SELECT cls.relname::text AS object_name"
            " FROM pg_catalog.pg_class cls"
            " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
            " WHERE ns.nspname = current_schema()"
            " UNION ALL"
            " SELECT proc.proname::text AS object_name"
            " FROM pg_catalog.pg_proc proc"
            " JOIN pg_catalog.pg_namespace ns ON ns.oid = proc.pronamespace"
            " WHERE ns.nspname = current_schema()"
            ") objects LIMIT 1"
        ).fetchone()
        if existing is not None:
            raise UniversePortabilityError(
                "the restore target database is not catalog-empty"
            )
    finally:
        conn.close()

    run_init_chain_at_dsn(
        bounded_dsn,
        emit=lambda line: _log.debug("trusted schema init: %s", line),
    )
    conn = db_backend.connect_psycopg(bounded_dsn)
    try:
        tables = conn.execute(
            "SELECT tablename::text FROM pg_catalog.pg_tables"
            " WHERE schemaname = current_schema() ORDER BY tablename"
        ).fetchall()
        if tables:
            identifiers = [sql.Identifier(str(row[0])) for row in tables]
            conn.execute(
                sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(identifiers)
                )
            )
        conn.commit()
    finally:
        conn.close()


def restore_universe(
    archive: Path | str,
    dsn: str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_restore: Optional[str] = None,
    finalize: Optional[Callable[[psycopg.Connection], None]] = None,
) -> ArchiveInspection:
    """Restore archive data into a fresh deployed-code schema transactionally.

    The caller must supply a catalog-empty database. This function first
    materializes the current trusted schema, clears only its bootstrap rows,
    and then enables TABLE DATA/SEQUENCE SET entries. Uploaded DDL is never
    executed, and no clean/drop flags can overwrite an existing universe.
    A trusted deployed-code ``finalize`` callback, when supplied, runs after
    data and constraints validate but before the restore transaction commits.
    """
    deadline = time.monotonic() + timeout_s
    inspection, catalog = _inspect_archive(
        archive,
        max_bytes=max_bytes,
        timeout_s=_remaining_timeout(deadline, "restore"),
        pg_restore=pg_restore,
    )
    executable = pg_restore or _postgres_executable("pg_restore")
    dbname = conninfo.conninfo_to_dict(dsn).get("dbname")
    if not dbname:
        raise UniversePortabilityError("the restore target DSN must name a database")
    _prepare_trusted_restore_schema(
        dsn,
        timeout_s=_remaining_timeout(deadline, "trusted schema preparation"),
    )
    restore_list = _write_restore_list(catalog)
    allowed_tables, allowed_sequences = _catalog_data_targets(catalog)
    try:
        _restore_via_libpq(
            executable=executable,
            archive=inspection.path,
            restore_list=restore_list,
            dsn=dsn,
            allowed_tables=allowed_tables,
            allowed_sequences=allowed_sequences,
            timeout_s=_remaining_timeout(deadline, "restore"),
            max_sql_bytes=max(
                64 * 1024 * 1024,
                max_bytes * DEFAULT_MAX_RESTORE_EXPANSION,
            ),
            finalize=finalize,
        )
    finally:
        restore_list.unlink(missing_ok=True)
    return inspection


def _write_restore_list(catalog: str) -> Path:
    """Write a private pg_restore list enabling only public data entries."""
    descriptor, raw_path = tempfile.mkstemp(prefix="yoke-universe-", suffix=".toc")
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for line in catalog.splitlines():
                if not line or line.startswith(";"):
                    stream.write(line + "\n")
                    continue
                kind, _namespace = _toc_kind_and_namespace(line)
                if kind in _RESTORED_DATA_TOC_KINDS:
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


def _unquote_identifier(value: str) -> str:
    if value.startswith('"'):
        return value[1:-1].replace('""', '"')
    return value


def _restore_target_columns(conn: object) -> dict[str, tuple[str, ...]]:
    rows = conn.execute(  # type: ignore[attr-defined]
        "SELECT cls.relname, att.attname"
        " FROM pg_catalog.pg_class cls"
        " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
        " JOIN pg_catalog.pg_attribute att ON att.attrelid = cls.oid"
        " WHERE ns.nspname = current_schema() AND cls.relkind = 'r'"
        " AND att.attnum > 0 AND NOT att.attisdropped AND att.attgenerated = ''"
        " ORDER BY cls.relname, att.attnum"
    ).fetchall()
    pending: dict[str, list[str]] = {}
    for table, column in rows:
        pending.setdefault(str(table), []).append(str(column))
    return {table: tuple(columns) for table, columns in pending.items()}


def _restore_target_sequences(conn: object) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(  # type: ignore[attr-defined]
            "SELECT sequencename FROM pg_catalog.pg_sequences"
            " WHERE schemaname = current_schema()"
        ).fetchall()
    }


def _compatible_restore_columns(
    table: str,
    archive_columns: Sequence[str],
    target_columns: Sequence[str],
) -> tuple[str, ...]:
    """Map one known historical COPY shape onto the trusted target table."""
    mapped = tuple(
        _ARCHIVE_COLUMN_RENAMES.get((table, column), column)
        for column in archive_columns
    )
    target = set(target_columns)
    if len(mapped) != len(set(mapped)):
        raise ArchiveInvalidError(
            f"the universe archive COPY columns are invalid for {table}"
        )
    unknown = set(mapped) - target
    missing = target - set(mapped)
    omittable = _ARCHIVE_OMITTABLE_TARGET_COLUMNS.get(table, frozenset())
    if unknown or not missing.issubset(omittable):
        raise ArchiveCompatibilityError(
            f"the universe archive COPY columns are not compatible with {table}"
            f" (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    return mapped


def _consume_restore_bytes(
    consumed: int,
    chunk: bytes,
    *,
    max_sql_bytes: int,
    deadline: float,
) -> int:
    if time.monotonic() >= deadline:
        raise UniversePortabilityError(
            "universe restore exhausted its end-to-end timeout"
        )
    total = consumed + len(chunk)
    if total > max_sql_bytes:
        raise ArchiveTooLargeError(
            "the expanded universe restore exceeds the"
            f" {max_sql_bytes}-byte safety limit"
        )
    return total


def _copy_restore_rows(
    source: object,
    copy: object,
    *,
    consumed: int,
    max_sql_bytes: int,
    deadline: float,
) -> int:
    """Stream one textual COPY body without buffering an unbounded row."""
    at_line_start = True
    while True:
        chunk = source.readline(_PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
        if not chunk:
            raise ArchiveInvalidError(
                "the universe archive COPY stream ended before its terminator"
            )
        consumed = _consume_restore_bytes(
            consumed,
            chunk,
            max_sql_bytes=max_sql_bytes,
            deadline=deadline,
        )
        if at_line_start and chunk in (b"\\.\n", b"\\.\r\n"):
            return consumed
        copy.write(chunk)  # type: ignore[attr-defined]
        at_line_start = chunk.endswith(b"\n")


def _apply_restore_stream(
    source: object,
    conn: object,
    *,
    allowed_tables: set[str],
    allowed_sequences: set[str],
    max_sql_bytes: int,
    deadline: float,
) -> None:
    """Apply only catalog-approved COPY data and sequence values via libpq."""
    target_columns = _restore_target_columns(conn)
    target_sequences = _restore_target_sequences(conn)
    expected_tables = set(target_columns)
    missing_tables = expected_tables - allowed_tables
    extra_tables = allowed_tables - expected_tables
    if (
        not missing_tables.issubset(_ARCHIVE_OMITTABLE_TARGET_TABLES)
        or extra_tables
    ):
        raise ArchiveCompatibilityError(
            "the universe archive TABLE DATA catalog does not match the"
            " deployed schema"
            f" (missing={sorted(missing_tables)},"
            f" extra={sorted(extra_tables)})"
        )
    missing_sequences = target_sequences - allowed_sequences
    extra_sequences = allowed_sequences - target_sequences
    if (
        not missing_sequences.issubset(_ARCHIVE_OMITTABLE_TARGET_SEQUENCES)
        or extra_sequences
    ):
        raise ArchiveCompatibilityError(
            "the universe archive SEQUENCE SET catalog does not match the"
            " deployed schema"
            f" (missing={sorted(missing_sequences)},"
            f" extra={sorted(extra_sequences)})"
        )
    observed_tables: set[str] = set()
    observed_sequences: set[str] = set()
    consumed = 0
    while True:
        raw = source.readline(64 * 1024)  # type: ignore[attr-defined]
        if not raw:
            break
        consumed = _consume_restore_bytes(
            consumed,
            raw,
            max_sql_bytes=max_sql_bytes,
            deadline=deadline,
        )
        if not raw.endswith(b"\n"):
            raise ArchiveInvalidError(
                "the universe archive contains an oversized restore control line"
            )
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArchiveInvalidError(
                "the universe archive restore metadata is not valid UTF-8"
            ) from exc
        if line in ("\n", "\r\n") or line.startswith("--"):
            continue
        if _RESTORE_SET_RE.fullmatch(line) is not None:
            continue
        if line.rstrip("\r\n") == _RESTORE_SEARCH_PATH:
            continue
        if _RESTORE_RESTRICT_RE.fullmatch(line) is not None:
            continue
        copy_match = _COPY_HEADER_RE.fullmatch(line)
        if copy_match is not None:
            schema_name = _unquote_identifier(copy_match.group("schema"))
            table_name = _unquote_identifier(copy_match.group("table"))
            archive_columns = [
                _unquote_identifier(value)
                for value in copy_match.group("columns").split(", ")
            ]
            if schema_name != "public" or table_name not in allowed_tables:
                raise ArchiveInvalidError(
                    "the universe archive COPY target is not enabled by its catalog"
                )
            if table_name in observed_tables:
                raise ArchiveInvalidError(
                    f"the universe archive repeats TABLE DATA for {table_name}"
                )
            known_columns = target_columns.get(table_name)
            if known_columns is None:
                raise ArchiveInvalidError(
                    f"the universe archive COPY columns are invalid for {table_name}"
                )
            columns = _compatible_restore_columns(
                table_name,
                archive_columns,
                known_columns,
            )
            statement = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
                sql.Identifier("public"),
                sql.Identifier(table_name),
                sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            )
            with conn.cursor().copy(statement) as copy:  # type: ignore[attr-defined]
                consumed = _copy_restore_rows(
                    source,
                    copy,
                    consumed=consumed,
                    max_sql_bytes=max_sql_bytes,
                    deadline=deadline,
                )
            observed_tables.add(table_name)
            continue
        setval_match = _SETVAL_RE.fullmatch(line)
        if setval_match is not None:
            sequence_name, raw_value, raw_called = setval_match.groups()
            if (
                sequence_name not in allowed_sequences
                or sequence_name not in target_sequences
            ):
                raise ArchiveInvalidError(
                    "the universe archive sequence target is not enabled"
                )
            if sequence_name in observed_sequences:
                raise ArchiveInvalidError(
                    f"the universe archive repeats SEQUENCE SET for {sequence_name}"
                )
            conn.execute(  # type: ignore[attr-defined]
                "SELECT pg_catalog.setval(%s::regclass, %s, %s)",
                (
                    f"public.{sequence_name}",
                    int(raw_value),
                    raw_called == "true",
                ),
            )
            observed_sequences.add(sequence_name)
            continue
        raise ArchiveInvalidError(
            "the universe archive generated executable restore syntax outside"
            " the COPY/sequence data boundary"
        )
    if observed_tables != allowed_tables:
        raise ArchiveInvalidError(
            "the universe archive TABLE DATA stream does not match its catalog"
            f" (missing={sorted(allowed_tables - observed_tables)},"
            f" extra={sorted(observed_tables - allowed_tables)})"
        )
    if observed_sequences != allowed_sequences:
        raise ArchiveInvalidError(
            "the universe archive SEQUENCE SET stream does not match its catalog"
            f" (missing={sorted(allowed_sequences - observed_sequences)},"
            f" extra={sorted(observed_sequences - allowed_sequences)})"
        )


def _restore_stream_worker(
    source: object,
    conn: object,
    *,
    allowed_tables: set[str],
    allowed_sequences: set[str],
    max_sql_bytes: int,
    deadline: float,
    errors: list[BaseException],
) -> None:
    try:
        _apply_restore_stream(
            source,
            conn,
            allowed_tables=allowed_tables,
            allowed_sequences=allowed_sequences,
            max_sql_bytes=max_sql_bytes,
            deadline=deadline,
        )
    except BaseException as exc:  # noqa: BLE001 - crosses a worker thread
        errors.append(exc)
    finally:
        source.close()  # type: ignore[attr-defined]


def _suspend_restore_constraints(
    conn: object,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Drop trusted FKs and suspend user triggers inside the load transaction."""
    foreign_keys = [
        (str(table), str(name), str(definition))
        for table, name, definition in conn.execute(  # type: ignore[attr-defined]
            "SELECT cls.relname, con.conname,"
            " pg_catalog.pg_get_constraintdef(con.oid, true)"
            " FROM pg_catalog.pg_constraint con"
            " JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid"
            " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
            " WHERE ns.nspname = current_schema() AND con.contype = 'f'"
            " ORDER BY cls.relname, con.conname"
        ).fetchall()
    ]
    triggers = [
        (str(table), str(name), str(enabled))
        for table, name, enabled in conn.execute(  # type: ignore[attr-defined]
            "SELECT cls.relname, trig.tgname, trig.tgenabled"
            " FROM pg_catalog.pg_trigger trig"
            " JOIN pg_catalog.pg_class cls ON cls.oid = trig.tgrelid"
            " JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace"
            " WHERE ns.nspname = current_schema() AND NOT trig.tgisinternal"
            " ORDER BY cls.relname, trig.tgname"
        ).fetchall()
    ]
    for table, name, _definition in foreign_keys:
        conn.execute(  # type: ignore[attr-defined]
            sql.SQL("ALTER TABLE {}.{} DROP CONSTRAINT {}").format(
                sql.Identifier("public"),
                sql.Identifier(table),
                sql.Identifier(name),
            )
        )
    for table, name, enabled in triggers:
        if enabled != "D":
            conn.execute(  # type: ignore[attr-defined]
                sql.SQL("ALTER TABLE {}.{} DISABLE TRIGGER {}").format(
                    sql.Identifier("public"),
                    sql.Identifier(table),
                    sql.Identifier(name),
                )
            )
    return foreign_keys, triggers


def _restore_constraints(
    conn: object,
    foreign_keys: list[tuple[str, str, str]],
    triggers: list[tuple[str, str, str]],
) -> None:
    """Recreate trusted integrity objects, validating all imported rows."""
    for table, name, definition in foreign_keys:
        conn.execute(  # type: ignore[attr-defined]
            sql.SQL("ALTER TABLE {}.{} ADD CONSTRAINT {} {}").format(
                sql.Identifier("public"),
                sql.Identifier(table),
                sql.Identifier(name),
                sql.SQL(definition),
            )
        )
    modes = {
        "O": sql.SQL("ENABLE"),
        "D": sql.SQL("DISABLE"),
        "R": sql.SQL("ENABLE REPLICA"),
        "A": sql.SQL("ENABLE ALWAYS"),
    }
    for table, name, enabled in triggers:
        mode = modes.get(enabled)
        if mode is None:
            raise UniversePortabilityError(
                f"trusted trigger {table}.{name} has unknown mode {enabled!r}"
            )
        conn.execute(  # type: ignore[attr-defined]
            sql.SQL("ALTER TABLE {}.{} {} TRIGGER {}").format(
                sql.Identifier("public"),
                sql.Identifier(table),
                mode,
                sql.Identifier(name),
            )
        )


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _quiesce_restore_worker(
    process: subprocess.Popen[bytes],
    worker: threading.Thread,
    connection: psycopg.Connection,
) -> bool:
    """Stop producer and COPY consumer before main-thread libpq teardown."""
    _terminate(process)
    if process.stdout is not None:
        process.stdout.close()
    worker.join(timeout=2)
    if worker.is_alive() and not connection.closed:
        try:
            connection.cancel()
        except psycopg.Error:
            pass
        worker.join(timeout=2)
    if worker.is_alive() and not connection.closed:
        connection.close()
        worker.join(timeout=2)
    return not worker.is_alive()


def _restore_via_libpq(
    *,
    executable: str,
    archive: Path,
    restore_list: Path,
    dsn: str,
    allowed_tables: set[str],
    allowed_sequences: set[str],
    timeout_s: float,
    max_sql_bytes: int,
    finalize: Optional[Callable[[psycopg.Connection], None]],
) -> None:
    """Generate data-only output and apply its payload through strict libpq."""
    restore_cmd = [
        executable,
        "--file=-",
        "--data-only",
        "--no-owner",
        "--no-privileges",
        "--no-comments",
        "--no-publications",
        "--no-security-labels",
        "--no-subscriptions",
        "--schema=public",
        "--use-list",
        str(restore_list),
        str(archive),
    ]
    parsed_dsn = conninfo.conninfo_to_dict(dsn)
    prior_options = str(parsed_dsn.get("options") or "").strip()
    timeout_ms = max(1, int(timeout_s * 1000))
    parsed_dsn["connect_timeout"] = str(max(1, min(30, math.ceil(timeout_s))))
    parsed_dsn["options"] = " ".join(
        value
        for value in (
            prior_options,
            f"-c statement_timeout={timeout_ms} -c lock_timeout={timeout_ms}"
            " -c search_path=public,pg_catalog",
        )
        if value
    )
    connection = psycopg.connect(conninfo.make_conninfo(**parsed_dsn))
    foreign_keys: list[tuple[str, str, str]] = []
    triggers: list[tuple[str, str, str]] = []
    restore: subprocess.Popen[bytes] | None = None
    try:
        foreign_keys, triggers = _suspend_restore_constraints(connection)
        restore = subprocess.Popen(
            restore_cmd,
            env=_subprocess_base_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        if restore is not None:
            _terminate(restore)
        connection.rollback()
        connection.close()
        raise UniversePortabilityError(
            f"universe restore client could not start: {exc}"
        ) from exc
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    assert restore is not None
    assert restore.stdout is not None and restore.stderr is not None
    stream_errors: list[BaseException] = []
    restore_stderr = bytearray()
    deadline = time.monotonic() + timeout_s
    workers = (
        threading.Thread(
            target=_restore_stream_worker,
            args=(restore.stdout, connection),
            kwargs={
                "allowed_tables": allowed_tables,
                "allowed_sequences": allowed_sequences,
                "max_sql_bytes": max_sql_bytes,
                "deadline": deadline,
                "errors": stream_errors,
            },
            daemon=True,
        ),
        threading.Thread(
            target=_bounded_diagnostic_reader,
            args=(restore.stderr, restore_stderr),
            daemon=True,
        ),
    )
    for worker in workers:
        worker.start()
    try:
        restore.wait(timeout=max(0.001, deadline - time.monotonic()))
        workers[0].join(timeout=max(0.001, deadline - time.monotonic()))
        if workers[0].is_alive():
            raise subprocess.TimeoutExpired(restore_cmd, timeout_s)
        if restore.returncode != 0 or stream_errors:
            connection.rollback()
        else:
            _restore_constraints(connection, foreign_keys, triggers)
            if finalize is not None:
                finalize(connection)
            connection.commit()
    except subprocess.TimeoutExpired as exc:
        worker_stopped = _quiesce_restore_worker(
            restore,
            workers[0],
            connection,
        )
        if worker_stopped and not connection.closed:
            connection.rollback()
        raise UniversePortabilityError(
            f"universe restore timed out after {timeout_s}s"
        ) from exc
    except BaseException:
        connection.rollback()
        raise
    finally:
        _terminate(restore)
        if workers[0].is_alive():
            _quiesce_restore_worker(restore, workers[0], connection)
        for worker in workers:
            worker.join(timeout=5)
        if not connection.closed:
            connection.close()
    if stream_errors:
        error = stream_errors[0]
        if isinstance(error, ArchiveTooLargeError):
            raise error
        if isinstance(error, UniversePortabilityError):
            raise error
        raise UniversePortabilityError(
            "universe restore stream failed before the transaction completed"
        ) from error
    if restore.returncode != 0:
        diagnostic = bytes(restore_stderr).decode("utf-8", errors="replace")
        diagnostic = "\n".join(diagnostic.strip().splitlines()[-12:])
        _log.error(
            "portable universe restore failed generator_rc=%s; stderr tail:\n%s",
            restore.returncode,
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
                table,
                f'SELECT COUNT(*) FROM "{table}"',
            )
            row = conn.execute(sql).fetchone()  # type: ignore[attr-defined]
            counts[table] = int(row[0])
        else:
            counts[table] = 0
    return counts


def all_table_row_counts(conn: object) -> dict[str, int]:
    """Raw-count every current-schema base table for fail-closed policy.

    Hosted callers classify each returned table as canonical birth baseline,
    maintenance-only state, or must-be-empty. A newly added table therefore
    appears automatically and is denied until that policy is taught, instead
    of silently escaping a hand-maintained content allowlist.
    """
    tables = [
        str(row[0])
        for row in conn.execute(  # type: ignore[attr-defined]
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema()"
            " AND table_type = 'BASE TABLE' ORDER BY table_name"
        ).fetchall()
    ]
    counts: dict[str, int] = {}
    for table in tables:
        row = conn.execute(  # type: ignore[attr-defined]
            sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier("public"),
                sql.Identifier(table),
            )
        ).fetchone()
        counts[table] = int(row[0])
    return counts


def converge_and_validate_restored_universe(
    dsn: str,
    *,
    expected_org_slug: str,
    expected_schema_fingerprint: str,
    timeout_s: float = DEFAULT_ARCHIVE_TIMEOUT_S,
) -> dict[str, object]:
    """Converge an imported DB and prove org identity + exact current schema."""
    from yoke_core.domain import db_backend, universe_capability_compatibility
    from yoke_core.domain.actor_permissions import seed_roles_and_permissions
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn
    from yoke_core.domain.schema_fingerprint import (
        fingerprint_portable_postgres_schema,
    )
    from yoke_core.domain.flow_init import create_or_replace_item_progress_view
    from yoke_core.domain.schema_migrations import _ensure_qa_runs_verdict_trigger
    from yoke_core.domain.schema_init import converge_core_schema
    from yoke_core.domain.schema_readiness import missing_readiness_tables

    parsed_dsn = conninfo.conninfo_to_dict(dsn)
    prior_options = str(parsed_dsn.get("options") or "").strip()
    bounded_options = (
        f"-c statement_timeout={max(1, int(timeout_s * 1000))}"
        f" -c lock_timeout={max(1, int(timeout_s * 1000))}"
        " -c search_path=public,pg_catalog"
    )
    parsed_dsn["options"] = " ".join(
        value for value in (prior_options, bounded_options) if value
    )
    parsed_dsn["connect_timeout"] = str(max(1, min(30, math.ceil(timeout_s))))
    bounded_dsn = conninfo.make_conninfo(**parsed_dsn)
    run_init_chain_at_dsn(
        bounded_dsn,
        emit=lambda line: _log.debug("restored schema converge: %s", line),
    )
    conn = db_backend.connect_psycopg(bounded_dsn)
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
        universe_capability_compatibility.validate_restored_capabilities(conn)
        actual_fingerprint = fingerprint_portable_postgres_schema(conn)
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
    "all_table_row_counts",
    "converge_and_validate_restored_universe",
    "dump_universe",
    "inspect_archive",
    "postgres_client_env",
    "restore_universe",
    "user_content_counts",
]

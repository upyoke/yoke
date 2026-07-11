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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, MutableMapping, Optional, Sequence

from psycopg import conninfo, pq

from yoke_core.domain import postgres_binaries, postgres_cluster


ARCHIVE_FORMAT = "pg_dump-custom"
ARCHIVE_MAGIC = b"PGDMP"
DEFAULT_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
DEFAULT_ARCHIVE_TIMEOUT_S = 600

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
    try:
        completed = subprocess.run(
            [
                executable,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file", str(dest),
            ],
            env=postgres_client_env(dsn),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        dest.unlink(missing_ok=True)
        detail = "timed out" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        raise UniversePortabilityError(f"universe export {detail}") from exc
    if completed.returncode != 0:
        dest.unlink(missing_ok=True)
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
    dbname = conninfo.conninfo_to_dict(dsn).get("dbname")
    if not dbname:
        raise UniversePortabilityError(
            "the restore target DSN must name a database"
        )
    try:
        completed = subprocess.run(
            [
                executable,
                # pg_restore requires explicit destination mode; the bare
                # database name is non-secret while every credential and
                # network/SSL option remains in the sanitized PG* env.
                "--dbname", str(dbname),
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                "--no-comments",
                "--no-publications",
                "--no-security-labels",
                "--no-subscriptions",
                "--schema=public",
                str(inspection.path),
            ],
            env=postgres_client_env(dsn),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail = "timed out" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        raise UniversePortabilityError(f"universe restore {detail}") from exc
    if completed.returncode != 0:
        raise UniversePortabilityError(
            "universe restore failed transactionally; the staging database"
            " was not accepted"
        )
    return inspection


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

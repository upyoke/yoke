"""Export the active universe to one self-contained portable archive.

One schema runs in every deployment mode, so moving a universe between
modes (local / self-host / hosted) is dump-and-restore; this module owns
the dump half. :func:`export_universe` produces ONE tar artifact
(:mod:`yoke_core.domain.universe_archive`) carrying the ``pg_dump``
custom-format payload and the freeze receipt that binds it — the receipt
travels inside the file, so the importer derives every verification
figure from the artifact itself instead of asking the operator.

The dump and its receipt are bound to one exported PostgreSQL snapshot:
authority watermarks are read inside the same ``REPEATABLE READ READ
ONLY`` view the dump exports, and the export refuses if the universe's
authority receipt changed while the dump ran.

Authority for this direct engine is DSN possession. Export is sanctioned when
the active machine-config connection is an unprotected Postgres connection whose
DSN this machine holds (the local universe's shape). The product CLI routes an
authenticated self-host HTTPS connection through the server-held authority and
routes hosted org admins to the dashboard's ``Move universe`` action. This
direct engine still refuses HTTPS connections and protected Postgres
connections. ``pg_dump`` resolves from the embedded engine's installed
binaries first, then ``PATH`` — the same rule the cluster lifecycle uses for
``initdb``/``pg_ctl``.
"""

from __future__ import annotations

import os
import tempfile
from yoke_contracts.timestamps import utc_now
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from yoke_core.domain import postgres_binaries
from yoke_core.domain import runtime_settings
from yoke_core.domain import universe_archive
from yoke_core.domain import universe_portability
from yoke_core.domain.universe_export_destination import (
    UniverseExportError,
    default_artifact_name,
    resolve_export_destination,
)

#: One tar carrying ``universe.dump`` + ``freeze-receipt.json``.
ARTIFACT_FORMAT = "universe-tar"

ARTIFACT_SUFFIX = universe_archive.ARTIFACT_SUFFIX

#: Machine-settings key capping the dump subprocess runtime.
EXPORT_TIMEOUT_SETTING = "universe_export_timeout_seconds"
DEFAULT_EXPORT_TIMEOUT_S = 600


def resolve_export_dsn() -> str:
    """The active connection's DSN when export is sanctioned, else raise.

    Sanction rule: an unprotected Postgres connection whose credentials this
    machine holds. HTTPS refuses because its server-side routing belongs to
    the product CLI, outside this direct-DSN engine. Protected Postgres
    refuses (operator-only).
    """
    from yoke_contracts.machine_config.schema import connection_is_protected
    from yoke_core.domain import db_backend, yoke_connected_env

    try:
        env = yoke_connected_env.load_active()
    except yoke_connected_env.ConnectedEnvError as exc:
        raise UniverseExportError(
            f"the machine's active connection could not be read: {exc}"
        ) from exc
    if env is None:
        raise UniverseExportError(
            "no active connection is configured on this machine; "
            "`yoke init --local` creates a local universe to export"
        )
    if env.backend != "postgres":
        raise UniverseExportError(
            f"the active connection {env.environment!r} is "
            f"{env.backend}-transport (hosted/self-host mode): this machine "
            "does not hold the universe database's DSN, and export requires "
            "DSN possession. A hosted org admin downloads from the "
            "dashboard's `Move universe` action; a self-host connection uses "
            "the authenticated server export endpoint. To export a machine-local "
            "universe, name its env for this invocation "
            "(`yoke --env local universe export`) or create one "
            "(`yoke init --local`)."
        )
    if connection_is_protected(env.config):
        raise UniverseExportError(
            f"the active connection {env.environment!r} is a protected "
            "Postgres connection: direct prod database authority is "
            "operator-only, so `yoke universe export` refuses it. Drive "
            "prod data through the sanctioned operator/admin surfaces."
        )
    try:
        resolved = yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        )
    except yoke_connected_env.ConnectedEnvError as exc:
        raise UniverseExportError(
            f"the active connection's DSN could not be resolved: {exc}"
        ) from exc
    return resolved.dsn


def export_universe(
    *,
    out: Optional[Union[str, Path]] = None,
    dsn: Optional[str] = None,
    exclude_artifacts: bool = False,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Export the active universe to one self-contained tar artifact.

    ``dsn=None`` resolves (and sanction-checks) the active connection; an
    explicit ``dsn`` is the injection seam for tests and operator tooling.
    ``out`` routing: ``None`` writes under the machine Yoke home exports folder; a
    trailing path separator always means a directory (created when
    missing — pass the raw string, ``Path`` drops the separator); an
    existing directory stays a directory; any other path is the target
    file. Directory targets get the default filename, which embeds the
    org slug and a UTC timestamp. Returns a payload naming the artifact
    path, size, org slug, archive format, and the dump payload's SHA-256
    (also recorded inside the artifact's freeze receipt).
    """
    from yoke_core.domain.source_authority_receipts import authority_receipt

    resolved_dsn = dsn if dsn is not None else resolve_export_dsn()
    _start_own_universe(resolved_dsn, emit)
    timeout = runtime_settings.get_seconds(
        EXPORT_TIMEOUT_SETTING,
        DEFAULT_EXPORT_TIMEOUT_S,
    )
    from yoke_core.domain.universe_artifact_transfer import collect_artifacts

    artifact_workspace = tempfile.TemporaryDirectory(prefix="yoke-export-files-")
    manifest, files = None, {}
    staged_dump: Optional[Path] = None
    try:
        conn = _snapshot_connection(resolved_dsn)
        try:
            identity = _universe_identity(conn)
            selected_org = str(identity["org"])
            dest = resolve_export_destination(out, selected_org)
            emit(f"  [universe-export] dumping org {selected_org!r} universe -> {dest}")
            frozen_at = utc_now()
            snapshot_id = str(conn.execute("SELECT pg_export_snapshot()").fetchone()[0])
            before = authority_receipt(conn)
            staged_dump = _staged_dump_path(dest)
            inspection = _dump_payload(
                resolved_dsn,
                staged_dump,
                timeout_s=timeout,
                snapshot=snapshot_id,
            )
            if not exclude_artifacts:
                manifest, files = collect_artifacts(conn, Path(artifact_workspace.name))
            after = authority_receipt(conn)
        finally:
            conn.close()
        if before["receipt_digest"] != after["receipt_digest"]:
            raise UniverseExportError(
                "the universe changed while it was being exported; retry once"
                " concurrent writers settle"
            )
        receipt = universe_archive.build_freeze_receipt(
            database=identity,
            frozen_at=frozen_at,
            authority=after,
            inspection=inspection,
            zero_writable_app_sessions=False,
        )
        if manifest is not None:
            from yoke_core.domain.universe_archive_artifacts import bind_manifest

            receipt = bind_manifest(receipt, manifest)
        try:
            artifact_bytes = universe_archive.pack_universe_archive(
                staged_dump,
                receipt,
                dest,
                artifact_manifest=manifest,
                artifact_files=files,
            )
        except universe_archive.UniverseArchiveError as exc:
            raise UniverseExportError(str(exc)) from exc
    finally:
        artifact_workspace.cleanup()
        _unlink_quietly(staged_dump)
    emit(
        f"  [universe-export] wrote {artifact_bytes} bytes"
        f" ({ARTIFACT_FORMAT}: {universe_archive.ARCHIVE_MEMBER_DUMP}"
        f" + {universe_archive.ARCHIVE_MEMBER_RECEIPT})"
    )
    return {
        "artifact": str(dest),
        "bytes": artifact_bytes,
        "format": ARTIFACT_FORMAT,
        "org": selected_org,
        "sha256": inspection.archive_sha256,
        "artifacts": {
            "included": len(files),
            "missing": sum(
                e["status"] == "missing" for e in (manifest or {}).get("entries", [])
            ),
        },
        "receipt_id": str(receipt["freeze_intent"]["receipt_id"]),
    }


def _dump_payload(
    dsn: str,
    destination: Path,
    *,
    timeout_s: int,
    snapshot: str,
) -> universe_portability.ArchiveInspection:
    """Run the snapshot-bound dump with operator-actionable errors."""
    try:
        return universe_portability.dump_universe(
            dsn,
            destination,
            timeout_s=timeout_s,
            snapshot=snapshot,
        )
    except universe_portability.UniversePortabilityError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise UniverseExportError(
                "pg_dump is missing: expected the embedded engine binaries at "
                f"{postgres_binaries.version_dir() / 'bin'} and found no "
                "pg_dump on PATH. Run `yoke local-postgres start` "
                "(or `yoke init --local`) to refetch the embedded engine."
            ) from exc
        raise UniverseExportError(
            f"universe export refused or failed safely: {exc}. If the embedded "
            "Postgres is stopped, `yoke local-postgres start` brings it up."
        ) from exc


def _start_own_universe(dsn: str, emit: Callable[[str], None]) -> None:
    """Start this machine's stopped embedded cluster before reading it."""
    from yoke_core.domain import local_universe, local_universe_autostart
    from yoke_core.domain.local_universe_convergence import serves_own_universe

    if not serves_own_universe(dsn):
        return
    try:
        local_universe_autostart.ensure_running(emit=emit)
    except local_universe.LocalUniverseError as exc:
        raise UniverseExportError(str(exc)) from exc


def _snapshot_connection(dsn: str):
    """One ``REPEATABLE READ READ ONLY`` view for receipts and the dump."""
    import psycopg

    from yoke_core.domain import db_backend

    try:
        conn = db_backend.connect_psycopg(dsn)
    except psycopg.OperationalError as exc:
        raise UniverseExportError(
            f"could not connect to the universe database: {exc}. If the "
            "embedded Postgres is stopped, `yoke local-postgres start` "
            "brings it up."
        ) from exc
    conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    conn.read_only = True
    return conn


def _universe_identity(conn) -> Dict[str, Any]:
    """The universe's database + org identity (also proves DB liveness)."""
    import psycopg

    row = conn.execute(
        "SELECT current_database(), oid FROM pg_database "
        "WHERE datname = current_database()"
    ).fetchone()
    try:
        org = conn.execute(
            "SELECT slug FROM organizations ORDER BY id LIMIT 1"
        ).fetchone()
    except psycopg.errors.UndefinedTable:
        org = None
    if org is None or not str(org[0] or "").strip():
        raise UniverseExportError(
            "the connected database carries no organization identity card, "
            "so it does not look like a bootstrapped Yoke universe "
            "(`yoke init --local` births one)"
        )
    return {
        "database": str(row[0]),
        "database_oid": int(row[1]),
        "org": str(org[0]).strip(),
    }


def _staged_dump_path(destination: Path) -> Path:
    """A private sibling file for the dump payload before it is packed."""
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".dump",
        dir=destination.parent,
    )
    os.close(descriptor)
    staged = Path(raw_path)
    staged.chmod(0o600)
    return staged


def _unlink_quietly(staged: Optional[Path]) -> None:
    if staged is not None:
        staged.unlink(missing_ok=True)


__all__ = [
    "ARTIFACT_FORMAT",
    "ARTIFACT_SUFFIX",
    "DEFAULT_EXPORT_TIMEOUT_S",
    "EXPORT_TIMEOUT_SETTING",
    "UniverseExportError",
    "default_artifact_name",
    "export_universe",
    "resolve_export_destination",
    "resolve_export_dsn",
]

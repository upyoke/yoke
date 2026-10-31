"""One snapshot-bound archive engine for every deployment mode."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import (
    postgres_binaries,
    runtime_settings,
    universe_archive,
    universe_portability,
)
from yoke_core.domain.universe_export_destination import (
    UniverseExportError,
    destination_unavailable,
    resolve_export_destination,
)

ARTIFACT_FORMAT = "universe-tar"
EXPORT_TIMEOUT_SETTING = "universe_export_timeout_seconds"
DEFAULT_EXPORT_TIMEOUT_S = 600


def snapshot_archive(
    *,
    dsn: str,
    out: Optional[Union[str, Path]] = None,
    writers_stopped: bool,
    max_bytes: int | None = None,
    include_artifacts: bool = True,
    source_identity: dict | None = None,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Pack a database snapshot and the receipt of its writer state."""
    from yoke_core.domain.source_authority_receipts import authority_receipt

    resolved_dsn = dsn
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
            if source_identity is not None:
                identity.update(source_identity)
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
            if include_artifacts:
                try:
                    manifest, files = collect_artifacts(
                        conn, Path(artifact_workspace.name)
                    )
                except universe_archive.UniverseArchiveError as exc:
                    raise UniverseExportError(str(exc)) from exc
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
            # Exclusive TEMPLATE copy plus source datallowconn=false proves
            # admission stayed fenced; later autovacuum does not add writers.
            zero_writable_app_sessions=writers_stopped,
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
                **({"max_bytes": max_bytes} if max_bytes is not None else {}),
            )
        except universe_archive.UniverseArchiveError as exc:
            raise UniverseExportError(str(exc)) from exc
    except OSError as exc:
        raise destination_unavailable(exc) from exc
    finally:
        artifact_workspace.cleanup()
        _unlink_quietly(staged_dump)
    members = [
        universe_archive.ARCHIVE_MEMBER_DUMP,
        universe_archive.ARCHIVE_MEMBER_RECEIPT,
    ]
    if manifest is not None:
        from yoke_core.domain.universe_archive_artifacts import MANIFEST

        members.append(MANIFEST)
        members.extend(sorted({"artifacts/" + key.split("/", 1)[0] for key in files}))
    emit(
        f"  [universe-export] wrote {artifact_bytes} bytes"
        f" ({ARTIFACT_FORMAT}: {' + '.join(members)})"
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
        "writers_stopped": writers_stopped,
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

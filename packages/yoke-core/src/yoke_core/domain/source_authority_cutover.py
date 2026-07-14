"""Attended production source-authority cutover operations.

The cutover boundary is a durable database CONNECT ACL owned by the attended
database administrator. Ordinary roles cannot override it per session. Export
uses one read-only REPEATABLE READ snapshot for both receipts and ``pg_dump``.
All public receipts omit connection strings and credentials.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import db_backend, universe_export, universe_portability
from yoke_core.domain import source_authority_connect_fence as connect_fence
from yoke_core.domain.source_authority_receipts import authority_receipt
from yoke_core.domain.source_freeze_intent import (
    file_sha256 as _file_sha256,
    freeze_intent,
    write_owner_only_json as _write_owner_only_json,
)


class SourceAuthorityCutoverError(RuntimeError):
    """The attended source-authority operation was refused safely."""


def resolve_prod_admin_dsn() -> str:
    """Resolve the configured ``*-db-admin`` authority without exposing it."""
    from yoke_contracts.machine_config.schema import connection_is_prod
    from yoke_core.domain import yoke_connected_env

    env = yoke_connected_env.load_active()
    if env is None:
        raise SourceAuthorityCutoverError("no machine connection is selected")
    if (
        env.backend != "postgres"
        or not env.environment.endswith("-db-admin")
        or not connection_is_prod(env.config)
    ):
        raise SourceAuthorityCutoverError(
            "source cutover requires an explicitly selected prod-db-admin "
            "Postgres connection"
        )
    try:
        return yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        ).dsn
    except yoke_connected_env.ConnectedEnvError as exc:
        raise SourceAuthorityCutoverError(
            f"prod-db-admin authority could not be resolved: {exc}"
        ) from exc


def begin(
    *, service_stop_receipt: str, dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Enter the database-enforced write freeze and return a stable receipt."""
    conn = _admin_connection(dsn)
    try:
        stop_receipt = str(service_stop_receipt or "").strip()
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", stop_receipt) is None:
            raise SourceAuthorityCutoverError(
                "begin requires a non-secret attended old-service stop receipt ID"
            )
        database = _database_identity(conn)
        frozen_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        fence = connect_fence.install_connect_fence(
            conn, frozen_at=frozen_at, service_stop_receipt=stop_receipt,
        )
        # The ACL must be visible before any session drain. If later proof or
        # receipt work fails, the committed fence remains recoverable via end.
        conn.commit()
        fence = connect_fence.drain_and_prove_connect_fence(conn)
        first = authority_receipt(conn)
        second = authority_receipt(conn)
        if first["receipt_digest"] != second["receipt_digest"]:
            raise SourceAuthorityCutoverError(
                "source watermarks changed while establishing quiescence"
            )
        return {
            "operation": "begin",
            "quiesced": True,
            "database": database,
            "terminated_connections": fence["terminated_other_sessions"],
            "stable_watermarks": True,
            "frozen_at": frozen_at,
            "service_stop_receipt": stop_receipt,
            "zero_writable_app_sessions": True,
            "admin_fence": fence,
            "authority": second,
        }
    except connect_fence.SourceConnectFenceError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        conn.close()


def status(*, dsn: Optional[str] = None) -> dict[str, Any]:
    """Return current freeze state and a deterministic authority receipt."""
    conn = _admin_connection(dsn)
    try:
        fence = connect_fence.connect_fence_status(conn)
        quiesced = bool(fence["active"])
        state = connect_fence.fence_state(conn)
        stop_receipt = None if state is None else state["service_stop_receipt"]
        return {
            "operation": "status",
            "quiesced": quiesced,
            "database": _database_identity(conn),
            "frozen_at": None if state is None else state["frozen_at"],
            "service_stop_receipt": stop_receipt,
            "zero_writable_app_sessions": bool(
                quiesced and stop_receipt
            ),
            "unauthorized_sessions": fence.get("unauthorized_sessions", []),
            "admin_fence": fence,
            "authority": authority_receipt(conn),
        }
    except connect_fence.SourceConnectFenceError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        conn.close()


def end(*, dsn: Optional[str] = None) -> dict[str, Any]:
    """Recover the source authority by removing its database write freeze."""
    conn = _admin_connection(dsn)
    try:
        # Recovery must remain possible when begin committed the ACL but later
        # drain/proof failed. Presence of the owner-only state, not a green
        # active proof, is the restoration precondition.
        if connect_fence.fence_state(conn) is None:
            raise SourceAuthorityCutoverError("source authority is not quiesced")
        database = _database_identity(conn)
        before = authority_receipt(conn)
        restored = connect_fence.restore_connect_fence(conn)
        conn.commit()
        return {
            "operation": "end",
            "quiesced": False,
            "database": database,
            "admin_fence": restored,
            "authority": before,
        }
    except connect_fence.SourceConnectFenceError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        conn.close()


def export_quiesced(
    *, out: str | Path, dsn: Optional[str] = None
) -> dict[str, Any]:
    """Export prod through admin authority only while its freeze is active."""
    resolved = dsn or resolve_prod_admin_dsn()
    conn = _admin_connection(resolved)
    try:
        conn.execute(
            "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        fence = connect_fence.connect_fence_status(conn)
        if not fence["active"]:
            raise SourceAuthorityCutoverError(
                "prod-admin universe export requires an active quiesce boundary"
            )
        state = connect_fence.fence_state(conn)
        if state is None or not state["service_stop_receipt"]:
            raise SourceAuthorityCutoverError(
                "prod-admin universe export requires the old-service stop receipt"
            )
        database = _database_identity(conn)
        frozen_at = None if state is None else state["frozen_at"]
        if frozen_at is None:
            raise SourceAuthorityCutoverError(
                "quiesce boundary has no frozen_at receipt"
            )
        snapshot_id = str(conn.execute("SELECT pg_export_snapshot()").fetchone()[0])
        before = authority_receipt(conn)
        report = universe_export.export_universe(
            out=out, dsn=resolved, snapshot=snapshot_id,
            org_slug=database["org"],
        )
        inspection = universe_portability.inspect_archive(report["artifact"])
        fence_after_dump = connect_fence.connect_fence_status(conn)
        if not fence_after_dump["active"]:
            raise SourceAuthorityCutoverError(
                "source CONNECT fence changed during universe export"
            )
        after_compact = authority_receipt(conn)
        after = authority_receipt(conn, include_content_digests=True)
    except connect_fence.SourceConnectFenceError as exc:
        raise SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        conn.close()
    if before["receipt_digest"] != after_compact["receipt_digest"]:
        raise SourceAuthorityCutoverError(
            "source authority changed during quiesced universe export"
        )
    catalog = universe_portability.archive_catalog_receipt(inspection)
    archive_sha = _file_sha256(Path(report["artifact"]))
    if str(catalog["archive_sha256"]) != archive_sha:
        raise SourceAuthorityCutoverError(
            "archive checksum changed between validation and receipt binding"
        )
    proof_conn = _admin_connection(resolved)
    try:
        final_fence = connect_fence.connect_fence_status(proof_conn)
    finally:
        proof_conn.close()
    if not final_fence["active"]:
        raise SourceAuthorityCutoverError(
            "source CONNECT fence was not durable after snapshot export"
        )
    intent = freeze_intent(
        database=database,
        frozen_at=frozen_at,
        authority=after,
        archive={
            "sha256": archive_sha,
            "bytes": int(report["bytes"]),
            "catalog_digest": str(catalog["catalog_digest"]),
        },
    )
    artifact = Path(report["artifact"])
    intent_path = artifact.with_suffix(artifact.suffix + ".source-freeze-intent.json")
    receipt_path = artifact.with_suffix(artifact.suffix + ".source-freeze-receipt.json")
    _write_owner_only_json(intent_path, intent)
    _write_owner_only_json(
        receipt_path,
        {"freeze_intent": intent, "source_authority": after, "catalog": catalog},
    )
    return {
        **report,
        "sha256": intent["archive"]["sha256"],
        "catalog": catalog,
        "source_authority": after,
        "stable_watermarks": True,
        "snapshot_proof": {
            "isolation": "repeatable-read-read-only",
            "snapshot_id_sha256": hashlib.sha256(
                snapshot_id.encode("utf-8")
            ).hexdigest(),
            "compact_before_digest": before["receipt_digest"],
            "compact_after_digest": after_compact["receipt_digest"],
            "connect_fence": final_fence,
        },
        "freeze_intent": intent,
        "freeze_intent_header": json.dumps(
            intent, sort_keys=True, separators=(",", ":"),
        ),
        "freeze_intent_path": str(intent_path),
        "receipt_sidecar_path": str(receipt_path),
    }


def _admin_connection(dsn: Optional[str]) -> object:
    conn = db_backend.connect_psycopg(dsn or resolve_prod_admin_dsn())
    return conn


def _database_identity(conn: object) -> dict[str, Any]:
    row = conn.execute(
        "SELECT current_database(), oid FROM pg_database "
        "WHERE datname = current_database()"
    ).fetchone()
    org = conn.execute(
        "SELECT slug FROM organizations ORDER BY id LIMIT 1"
    ).fetchone()
    return {"database": str(row[0]), "database_oid": int(row[1]), "org": str(org[0])}


__all__ = ["SourceAuthorityCutoverError", "authority_receipt", "begin", "end",
           "export_quiesced", "freeze_intent", "resolve_prod_admin_dsn", "status"]

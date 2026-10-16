"""Snapshot upload expiry and custody without stored leases."""

from contextlib import contextmanager
from datetime import timedelta
import hashlib

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.retention_table_policies import Cleanup


def upload_lock_key(upload_id):
    digest = hashlib.sha256(f"snapshot-upload:{upload_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
def upload_lock(conn, upload_id):
    """Cover internal commits and separate materialization connections too."""
    postgres = db_backend.connection_is_postgres(conn)
    key = upload_lock_key(upload_id)
    if postgres:
        acquired = conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
        if not acquired:
            raise ValueError(
                "snapshot_upload_busy: another operation owns this upload. "
                "Recovery: retry snapshot sync or universe prune after that operation finishes."
            )
    try:
        yield
    finally:
        if postgres:
            # A failed statement can leave the transaction aborted; unlock on
            # the same connection only after clearing that state.
            try:
                conn.rollback()
                conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
                conn.commit()
            except Exception:
                # Closing releases session custody even if the connection can
                # no longer answer. Never turn acknowledged commits into lost
                # counts merely because explicit unlock could not be read.
                conn.close()


def require_fresh_upload(conn, upload_id):
    from yoke_core.domain.project_snapshot_sync_refusals import ChunkUploadMissingError
    from yoke_core.domain.universe_retention import read_policy

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT created_at FROM path_snapshot_sync_uploads WHERE upload_id={p}",
        (upload_id,),
    ).fetchone()
    policy, _ = read_policy(conn)
    if row is None or parse_instant(row[0]) < utc_now() - timedelta(
        days=policy.windows["snapshot_uploads"]
    ):
        raise ChunkUploadMissingError(
            "snapshot_upload_expired_or_missing: staging lasts at most seven days. "
            "Recovery: restart project snapshot sync with a new upload."
        )


def upload_policy(policy, cutoff):
    return Cleanup(
        "path_snapshot_sync_uploads",
        ("upload_id",),
        "t.created_at<%s",
        (cutoff - timedelta(days=policy.windows["snapshot_uploads"]),),
        children=(("path_snapshot_sync_upload_chunks", "upload_id", "upload_id"),),
        reason="active upload operations are protected; expired staging requires a fresh sync",
    )

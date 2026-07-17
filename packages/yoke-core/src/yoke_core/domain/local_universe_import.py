"""Restore one portable archive into the active machine-local universe.

Local mode owns its Postgres DSN, so it can use the same trusted-data restore
engine as self-host import without manufacturing a server credential.  The
archive supplies data only: deployed code materializes the destination schema,
uploaded DDL is never executed, imported API/web credentials are revoked, and
the current machine owner receives org-admin authority before commit.
"""

from __future__ import annotations

import getpass
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg

from yoke_contracts.machine_config.schema import connection_is_prod
from yoke_core.domain import (
    actors,
    db_backend,
    json_helper,
    universe_archive,
    universe_portability,
    universe_startup_lock,
    yoke_connected_env,
)
from yoke_core.domain.actor_permissions import ROLE_ADMIN


class LocalUniverseImportError(RuntimeError):
    """The active local universe could not be safely replaced."""


def resolve_local_import_dsn() -> str:
    """Return the active local universe DSN or refuse every other mode."""
    try:
        env = yoke_connected_env.load_active()
    except yoke_connected_env.ConnectedEnvError as exc:
        raise LocalUniverseImportError(
            f"the machine's active connection could not be read: {exc}"
        ) from exc
    if env is None:
        raise LocalUniverseImportError(
            "no active connection is configured; `yoke init --local` creates "
            "the local universe that `yoke universe import` can replace"
        )
    if env.environment != "local" or env.backend != "postgres":
        raise LocalUniverseImportError(
            f"the active connection {env.environment!r} is not the machine-local "
            "universe; switch with `yoke env use local` before importing"
        )
    if connection_is_prod(env.config):
        raise LocalUniverseImportError(
            "the active local connection is marked production; direct import "
            "is refused"
        )
    try:
        resolved = yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        )
    except yoke_connected_env.ConnectedEnvError as exc:
        raise LocalUniverseImportError(
            f"the local universe DSN could not be resolved: {exc}"
        ) from exc
    return resolved.dsn


def import_universe(
    archive: Path | str,
    *,
    dsn: Optional[str] = None,
    max_bytes: int = universe_portability.DEFAULT_MAX_ARCHIVE_BYTES,
) -> dict[str, object]:
    """Replace the local universe with ``archive`` and return a safe receipt."""
    selected = _validated_archive_path(archive)
    resolved_dsn = dsn or resolve_local_import_dsn()
    owner: dict[str, object] = {}
    try:
        with universe_archive.unpacked_universe_archive(
            selected,
            max_dump_bytes=max_bytes,
        ) as (dump, receipt):
            binding = universe_archive.verify_receipt_binds_dump(receipt, dump)
            receipt_org = str(
                receipt.get("freeze_intent", {})
                .get("database", {})
                .get("org")
                or ""
            )

            def finalize(conn: psycopg.Connection) -> None:
                owner.update(_prepare_local_owner(conn))
                if receipt_org and receipt_org != owner["org"]:
                    raise LocalUniverseImportError(
                        "the archive freeze receipt names org "
                        f"{receipt_org!r} but the enclosed universe is org "
                        f"{owner['org']!r}"
                    )

            with universe_startup_lock.exclusive_import_guard(resolved_dsn):
                inspection = universe_portability.restore_universe(
                    dump,
                    resolved_dsn,
                    max_bytes=max_bytes,
                    finalize=finalize,
                )
    except (
        universe_archive.UniverseArchiveError,
        universe_portability.UniversePortabilityError,
        universe_startup_lock.UniverseStartupBusy,
    ) as exc:
        raise LocalUniverseImportError(str(exc)) from exc
    except OSError as exc:
        raise LocalUniverseImportError(
            "the local universe archive could not be read safely"
        ) from exc
    except psycopg.Error as exc:
        raise LocalUniverseImportError(
            "the local universe database restore failed"
        ) from exc
    if not owner:
        raise LocalUniverseImportError(
            "the restore completed without establishing the local owner"
        )
    return {
        "ok": True,
        **owner,
        "archive": {
            "path": str(selected.expanduser().resolve()),
            "bytes": inspection.size_bytes,
            "sha256": binding["sha256"],
            "dumped_from_postgres": inspection.dumped_from_postgres,
            "dumped_by_pg_dump": inspection.dumped_by_pg_dump,
            "table_entries": inspection.table_entries,
        },
    }


def _prepare_local_owner(conn: psycopg.Connection) -> dict[str, object]:
    organizations = conn.execute(
        "SELECT id, slug FROM organizations ORDER BY id"
    ).fetchall()
    if len(organizations) != 1:
        raise LocalUniverseImportError(
            "a local universe import requires exactly one organization; "
            f"the archive contains {len(organizations)}"
        )
    org_id, org_slug = int(organizations[0][0]), str(organizations[0][1])
    role = conn.execute(
        "SELECT id FROM roles WHERE name = %s",
        (ROLE_ADMIN,),
    ).fetchone()
    if role is None:
        raise LocalUniverseImportError("the imported universe has no admin role")

    label = _machine_owner_label()
    actor = conn.execute(
        "SELECT a.id, a.kind FROM actor_labels al "
        "JOIN actors a ON a.id = al.actor_id "
        "WHERE al.surface = %s AND al.label = %s",
        (actors.GITHUB_LABEL_SURFACE, label),
    ).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if actor is not None:
        if str(actor[1]) != "human":
            raise LocalUniverseImportError(
                "the machine owner label belongs to a non-human actor"
            )
        actor_id = int(actor[0])
    else:
        row = conn.execute(
            "INSERT INTO actors (kind, system_component, created_at) "
            "VALUES ('human', NULL, %s) RETURNING id",
            (now,),
        ).fetchone()
        if row is None:
            raise LocalUniverseImportError(
                "the local owner actor could not be created"
            )
        actor_id = int(row[0])
        conn.execute(
            "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (actor_id, actors.GITHUB_LABEL_SURFACE, label, now),
        )

    conn.execute(
        "INSERT INTO actor_org_roles "
        "(actor_id, org_id, role_id, granted_at, granted_by_actor_id) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT(actor_id, org_id, role_id) DO NOTHING",
        (actor_id, org_id, int(role[0]), now, actor_id),
    )
    metadata = json_helper.dumps_compact({"reason": "local_universe_import"})
    revoked_tokens = _revoke_api_tokens(
        conn,
        actor_id=actor_id,
        metadata=metadata,
        now=now,
    )
    revoked_sessions = conn.execute(
        "WITH revoked AS ("
        "UPDATE web_sessions SET revoked_at = %s "
        "WHERE revoked_at IS NULL RETURNING 1"
        ") SELECT COUNT(*) FROM revoked",
        (now,),
    ).fetchone()
    return {
        "org": org_slug,
        "actor_id": actor_id,
        "actor_label": label,
        "revoked_token_count": revoked_tokens,
        "revoked_web_session_count": int(revoked_sessions[0] or 0),
    }


def _revoke_api_tokens(
    conn: psycopg.Connection,
    *,
    actor_id: int,
    metadata: str,
    now: str,
) -> int:
    row = conn.execute(
        "WITH revoked AS ("
        "UPDATE api_tokens SET status = 'revoked', revoked_at = %s "
        "WHERE status = 'active' RETURNING id"
        "), audited AS ("
        "INSERT INTO api_token_audit "
        "(api_token_id, actor_id, project_id, event_type, outcome, "
        "permission_key, diagnostic_metadata, created_at) "
        "SELECT id, %s, NULL, 'revoked', 'success', NULL, %s, %s "
        "FROM revoked RETURNING 1"
        ") SELECT COUNT(*) FROM audited",
        (now, actor_id, metadata, now),
    ).fetchone()
    return int(row[0] or 0)


def _machine_owner_label() -> str:
    try:
        return getpass.getuser().strip() or actors.DEFAULT_LOCAL_HUMAN_LABEL
    except Exception:
        return actors.DEFAULT_LOCAL_HUMAN_LABEL


def _validated_archive_path(archive: Path | str) -> Path:
    selected = Path(archive).expanduser()
    try:
        info = selected.lstat()
    except OSError as exc:
        raise LocalUniverseImportError(
            f"the universe archive is missing or unreadable: {selected}"
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise LocalUniverseImportError(
            f"the universe archive must be a regular file, not a symlink: {selected}"
        )
    getuid = getattr(os, "geteuid", None)
    if callable(getuid) and (info.st_uid != getuid() or info.st_nlink != 1):
        raise LocalUniverseImportError(
            "the universe archive must be a current-owner, single-link regular file"
        )
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise LocalUniverseImportError(
            f"the universe archive must be owner-only; run `chmod 600 {selected}`"
        )
    return selected


__all__ = [
    "LocalUniverseImportError",
    "import_universe",
    "resolve_local_import_dsn",
]

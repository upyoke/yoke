"""Non-secret metadata updates for machine-local capability secrets."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.machine_config.capability_secrets import (
    SSH_CAPABILITY,
    SSH_PRIVATE_KEY_SECRET_KEY,
)

from yoke_core.domain import json_helper
from yoke_core.domain.db_helpers import iso8601_now, query_one


def sync_machine_secret_metadata(
    conn,
    project_id: int,
    cap_type: str,
    key: str,
    path: Path,
) -> None:
    """Update non-secret DB metadata after writing a local secret file."""
    if cap_type != SSH_CAPABILITY or key != SSH_PRIVATE_KEY_SECRET_KEY:
        return
    _set_ssh_key_path(conn, project_id, path)


def _set_ssh_key_path(conn, project_id: int, key_path: Path) -> None:
    row = query_one(
        conn,
        "SELECT COALESCE(settings, '{}') AS settings "
        "FROM project_capabilities WHERE project_id=%s AND type=%s",
        (project_id, SSH_CAPABILITY),
    )
    if row is None:
        settings = {"key_path": str(key_path)}
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) VALUES (%s, %s, %s, %s)",
            (
                project_id,
                SSH_CAPABILITY,
                json_helper.dumps_compact(settings),
                iso8601_now(),
            ),
        )
        return

    loaded = json_helper.loads_text(str(row["settings"] or "{}"))
    if not isinstance(loaded, dict):
        raise ValueError("ssh capability settings must be a JSON object")
    loaded["key_path"] = str(key_path)
    conn.execute(
        "UPDATE project_capabilities SET settings=%s "
        "WHERE project_id=%s AND type=%s",
        (json_helper.dumps_compact(loaded), project_id, SSH_CAPABILITY),
    )


__all__ = ["sync_machine_secret_metadata"]

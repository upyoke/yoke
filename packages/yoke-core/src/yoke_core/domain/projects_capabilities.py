"""Project capability surface: capability listings and secrets.

Owner: ``yoke_core.domain.projects`` (orchestration layer).  Public
symbols are re-exported from the parent so existing callers via
``yoke_core.domain.projects`` continue to work unchanged. The
per-capability settings read/write family (get/set/merge, value-CAS
protected) lives in
:mod:`yoke_core.domain.projects_capabilities_settings`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional

from yoke_contracts.machine_config.capability_secrets import (
    is_machine_local_capability_secret,
)

from yoke_core.domain import capability_machine_secrets
from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_one,
    query_rows,
)
from yoke_core.domain.project_identity import resolve_project, resolve_project_id


# ---------------------------------------------------------------------------
# capabilities-by-type
# ---------------------------------------------------------------------------

def list_capability_settings_by_type(
    cap_type: str,
    db_path: Optional[str] = None,
) -> List[str]:
    """Return every non-sensitive settings JSON for a given capability type.

    Used by cross-project capability lookups such as the remote-browser
    config scan in ``browser_worker`` — there is no single project that
    owns those rows, so we query ``project_capabilities`` by type and
    return the list in table order.
    """
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            "SELECT COALESCE(settings, '{}') AS settings FROM project_capabilities "
            "WHERE type=%s ORDER BY project_id",
            (cap_type,),
        )
        return [str(row["settings"]) for row in rows if row["settings"]]
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# capability-list
# ---------------------------------------------------------------------------

def cmd_capability_list(
    project: str,
    db_path: Optional[str] = None,
) -> str:
    """List capability type names (newline-separated)."""
    conn = connect(db_path)
    try:
        project_id = resolve_project_id(conn, project)
        rows = query_rows(
            conn,
            "SELECT type FROM project_capabilities WHERE project_id=%s ORDER BY type",
            (project_id,),
        )
        return "\n".join(str(r["type"]) for r in rows)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# capability-get-secret
# ---------------------------------------------------------------------------

def cmd_capability_get_secret(
    project: str,
    cap_type: str,
    key: str,
    db_path: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Optional[str]:
    """Retrieve a capability secret value.

    ``aws-admin`` secrets are machine-local under
    ``~/.yoke/secrets/capability-secrets``. Other capability secrets,
    including the GitHub PAT, live in :data:`capability_secrets` with
    ``source='literal'``.

    When ``conn`` is supplied the read happens against the caller's
    connection and it is left open. Without ``conn`` the function opens a
    fresh connection via ``db_path`` (or canonical ``YOKE_DB``) and
    closes it before returning — existing callers stay backward compatible.
    """
    own_conn = conn is None
    if own_conn:
        conn = connect(db_path)
    try:
        if is_machine_local_capability_secret(cap_type, key):
            ident = resolve_project(conn, project, required=True)
            assert ident is not None
            return capability_machine_secrets.read_machine_capability_secret(
                ident.slug, cap_type, key,
            )
        project_id = resolve_project_id(conn, project)
        row = query_one(
            conn,
            "SELECT value, source FROM capability_secrets "
            "WHERE project_id=%s AND type=%s AND key=%s",
            (project_id, cap_type, key),
        )

        if row is None:
            return None

        value = row["value"]
        source = row["source"]

        if source != "literal":
            raise ValueError(
                "capability secret has unsupported source="
                f"{source!r}; re-import it with `yoke projects "
                "capability secret set ... VALUE|--value-file|--value-stdin`"
            )
        return value
    finally:
        if own_conn:
            conn.close()


# ---------------------------------------------------------------------------
# capability-set-secret
# ---------------------------------------------------------------------------

def capability_secret_value_from_args(args: Any) -> str:
    sources = [
        args.value is not None,
        args.value_file is not None,
        args.value_stdin,
    ]
    if sum(1 for source in sources if source) != 1:
        raise ValueError(
            "exactly one secret value source is required: VALUE, "
            "--value-file, or --value-stdin"
        )
    if args.value is not None:
        value = str(args.value).strip()
    elif args.value_file is not None:
        selected = Path(args.value_file).expanduser()
        if not selected.is_file():
            raise FileNotFoundError(f"secret file not found: {selected}")
        value = selected.read_text(encoding="utf-8").strip()
    else:
        value = sys.stdin.read().strip()
    if not value:
        raise ValueError("secret value is empty")
    return value


def cmd_capability_set_secret(
    project: str,
    cap_type: str,
    key: str,
    value: str = "",
    source: str = "literal",
    db_path: Optional[str] = None,
) -> str:
    """Upsert a secret for a capability."""
    if source != "literal":
        raise ValueError(
            "Error: capability secrets must be imported into Yoke's "
            "capability_secrets store as source='literal'"
        )
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        if is_machine_local_capability_secret(cap_type, key):
            path = capability_machine_secrets.store_machine_capability_secret(
                ident.slug, cap_type, key, value,
            )
            from yoke_core.domain.projects_machine_secret_metadata import (
                sync_machine_secret_metadata,
            )

            sync_machine_secret_metadata(conn, ident.id, cap_type, key, path)
            conn.execute(
                "DELETE FROM capability_secrets "
                "WHERE project_id=%s AND type=%s AND key=%s",
                (ident.id, cap_type, key),
            )
            conn.commit()
            return (
                f"Set machine-local secret '{key}' for capability "
                f"'{cap_type}' on project '{ident.slug}' at {path}"
            )
        project_id = ident.id
        conn.execute(
            "INSERT INTO capability_secrets "
            "(project_id, type, key, value, source, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(project_id, type, key) DO UPDATE SET value=%s, source=%s",
            (project_id, cap_type, key, value, "literal", iso8601_now(),
             value, "literal"),
        )
        conn.commit()
        return (
            f"Set secret '{key}' for capability '{cap_type}' "
            f"on project '{project}' (source: literal)"
        )
    finally:
        conn.close()


def cmd_capability_mark_machine_secret_file(
    project: str,
    cap_type: str,
    key: str,
    path: str,
    db_path: Optional[str] = None,
) -> str:
    """Record non-secret metadata for an already-written local secret file."""
    if not is_machine_local_capability_secret(cap_type, key):
        raise ValueError(f"{cap_type}.{key} is not a machine-local secret")
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        from yoke_core.domain.projects_machine_secret_metadata import (
            sync_machine_secret_metadata,
        )

        sync_machine_secret_metadata(conn, ident.id, cap_type, key, Path(path))
        conn.execute(
            "DELETE FROM capability_secrets "
            "WHERE project_id=%s AND type=%s AND key=%s",
            (ident.id, cap_type, key),
        )
        conn.commit()
        return (
            f"Recorded machine-local secret file for '{key}' capability "
            f"'{cap_type}' on project '{ident.slug}'"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# capability-list-secrets
# ---------------------------------------------------------------------------

def cmd_capability_list_secrets(
    project: str,
    cap_type: str,
    db_path: Optional[str] = None,
) -> str:
    """List secret key names (newline-separated)."""
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project, required=True)
        assert ident is not None
        if is_machine_local_capability_secret(cap_type):
            keys = capability_machine_secrets.list_machine_capability_secret_keys(
                ident.slug, cap_type,
            )
        else:
            keys = []
        project_id = ident.id
        rows = query_rows(
            conn,
            "SELECT key FROM capability_secrets WHERE project_id=%s AND type=%s ORDER BY key",
            (project_id, cap_type),
        )
        keys.extend(
            str(r["key"]) for r in rows
            if not is_machine_local_capability_secret(cap_type, str(r["key"]))
        )
        return "\n".join(sorted(set(keys)))
    finally:
        conn.close()

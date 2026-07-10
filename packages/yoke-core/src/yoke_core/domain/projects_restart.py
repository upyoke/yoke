"""Project init and migration lifecycle management.

Owns ``cmd_init`` (table DDL + idempotent column migrations + config-split
fixup) and ``cmd_resolve_deploy_envs``.  Reference-data seeding lives in
:mod:`yoke_core.domain.projects_seed_data`; the orchestration layer in
:mod:`yoke_core.domain.projects` re-exports both surfaces.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.db_helpers import connect, iso8601_now, query_rows
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.project_github_capability_settings import (
    normalize_github_capability_type,
)
from yoke_core.domain.project_github_auth_models import GITHUB_CAPABILITY_TYPE
from yoke_core.domain.projects_restart_schema import _INIT_TABLES_SQL
from yoke_core.domain.projects_seed_data import seed_all
from yoke_core.domain.retired_schema_registry import guard_add_column
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.schema_common import (
    _column_exists as _schema_column_exists,
    _table_exists as _schema_table_exists,
)
from yoke_core.domain.sql_json import json_get


_RESTART_PROJECT = "yoke"
_RESTART_CALLER = "yoke_core.domain.projects_restart"


def _placeholder(conn) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """Idempotent ``ALTER TABLE ... ADD COLUMN`` with retired-schema guard.

    Skips the ADD COLUMN (and emits
    :event:`RetiredSchemaResurrectionAttempt`) when the column is
    registered in ``runtime/api/domain/retired_schema_surfaces.yaml``. Skipping is
    preferred over hard failure so operator-invoked recovery scenarios
    do not block on the guard.
    """
    if _has_column(conn, table, column):
        return
    if not guard_add_column(_RESTART_PROJECT, table, column, caller=_RESTART_CALLER):
        return
    conn.execute(ddl)
    conn.commit()


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _table_exists(conn, table_name: str) -> bool:
    return _schema_table_exists(conn, table_name)


def _has_column(conn, table_name: str, column_name: str) -> bool:
    return _schema_column_exists(conn, table_name, column_name)


# Secret-key heuristic patterns used by config-split migration
_SECRET_PATTERNS = ("token", "secret", "password", "api_key", "access_key", "private_key")


# ---------------------------------------------------------------------------
# Config-split migration helper
# ---------------------------------------------------------------------------

def _migrate_config_split(conn) -> None:
    """Split the unified ``config`` JSON into ``settings`` + ``capability_secrets``.

    Uses ``capability_templates.required_config`` to classify keys as secret
    or non-secret.  Keys not declared in any template fall back to a
    heuristic (name contains token/secret/password/api_key/etc.).
    """
    # Load templates for secret-key lookup
    templates: Dict[str, set] = {}
    template_all_keys: Dict[str, set] = {}
    p = _placeholder(conn)
    for row in query_rows(conn, "SELECT id, required_config FROM capability_templates"):
        try:
            rc = json.loads(row["required_config"])
            templates[row["id"]] = {item["key"] for item in rc if item.get("secret")}
            template_all_keys[row["id"]] = {item["key"] for item in rc}
        except (json.JSONDecodeError, KeyError):
            templates[row["id"]] = set()
            template_all_keys[row["id"]] = set()

    # Run the back-fill against rows whose settings are still empty so
    # this helper stays a safe no-op on a fully migrated DB.
    rows = query_rows(
        conn,
        "SELECT project_id, type, COALESCE(settings, '{}') AS settings FROM project_capabilities "
        "WHERE settings IS NULL OR settings='{}'",
    )

    for row in rows:
        proj, ctype, config_str = row["project_id"], row["type"], row["settings"]
        if normalize_github_capability_type(str(ctype)) == GITHUB_CAPABILITY_TYPE:
            continue
        try:
            config = json.loads(config_str)
        except json.JSONDecodeError:
            continue

        secret_keys = templates.get(ctype, set())
        all_tmpl_keys = template_all_keys.get(ctype, set())

        settings: Dict[str, Any] = {}
        secrets: Dict[str, Any] = {}
        for k, v in config.items():
            is_secret = k in secret_keys
            if not is_secret and k not in all_tmpl_keys:
                is_secret = any(p in k.lower() for p in _SECRET_PATTERNS)
            if is_secret:
                secrets[k] = v
            else:
                settings[k] = v

        conn.execute(
            f"UPDATE project_capabilities SET settings={p} WHERE project_id={p} AND type={p}",
            (json.dumps(settings), proj, ctype),
        )

        for sk, sv in secrets.items():
            conn.execute(
                "INSERT INTO capability_secrets "
                "(project_id, type, key, value, source, created_at) "
                f"VALUES ({p}, {p}, {p}, {p}, 'literal', {p}) "
                "ON CONFLICT(project_id, type, key) DO NOTHING",
                (proj, ctype, sk, str(sv), iso8601_now()),
            )

    conn.commit()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(db_path: Optional[str] = None) -> None:
    """Create project-registry tables, run migrations, and seed data."""
    conn = connect(db_path)
    try:
        execute_schema_script(conn, _INIT_TABLES_SQL)

        # --- Idempotent migrations (retired-schema-guarded ADD COLUMN) ---
        _ensure_column(
            conn, "projects", "emoji",
            "ALTER TABLE projects ADD COLUMN emoji TEXT DEFAULT ''",
        )
        _ensure_column(
            conn, "projects", "github_repo",
            "ALTER TABLE projects ADD COLUMN github_repo TEXT",
        )
        _ensure_column(
            conn, "project_capabilities", "settings",
            "ALTER TABLE project_capabilities ADD COLUMN settings TEXT DEFAULT '{}'",
        )
        _ensure_column(
            conn, "ephemeral_environments", "deployed_sha",
            "ALTER TABLE ephemeral_environments ADD COLUMN deployed_sha TEXT",
        )

        # The live schema now uses ``settings`` + ``capability_secrets`` as
        # the only writeable capability contract.  The historical
        # config-split fixup that ran here is retired.

        # --- Seed reference data ---
        # The seed pipeline runs against ``conn``; this function owns the
        # surrounding transaction.
        seed_all(conn, db_path)
        conn.commit()

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# resolve-deploy-envs
# ---------------------------------------------------------------------------

def cmd_resolve_deploy_envs(
    project: str,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Resolve valid deployment environments for a project.

    Sources (in order, first non-empty wins for DB tables):
    1. ``environments`` via ``sites`` table
       UNION ``deployment_flows.target_env``
    2. ``project_capabilities`` with type ``deployment_environments`` (JSON config)

    Returns newline-separated environment names (sorted), or None if none found.
    """
    conn = connect(db_path)
    try:
        ident = resolve_project(conn, project)
        assert ident is not None
        p = _placeholder(conn)
        parts: List[str] = []

        if _table_exists(conn, "environments") and _table_exists(conn, "sites"):
            parts.append(
                "SELECT e.name AS env_name "
                "FROM environments e "
                "JOIN sites s ON s.id = e.site "
                f"WHERE s.project_id = {p}"
            )

        if _table_exists(conn, "deployment_flows"):
            parts.append(
                "SELECT df.target_env AS env_name "
                "FROM deployment_flows df "
                f"WHERE df.project_id = {p} "
                "AND df.target_env IS NOT NULL "
                "AND df.target_env <> ''"
            )

        if parts:
            union_sql = " UNION ".join(parts)
            full_sql = f"SELECT DISTINCT env_name FROM ({union_sql}) ORDER BY env_name"
            # Build params: one ? per part
            params = tuple(ident.id for _ in parts)
            rows = query_rows(conn, full_sql, params)
            if rows:
                return "\n".join(str(r["env_name"]) for r in rows)

        # Source 3: project_capabilities deployment_environments settings
        # (JSON array under .environments). SQLite's ``json_each`` table
        # function has no Postgres equivalent: Postgres iterates the array with
        # ``jsonb_array_elements`` and reads each scalar string element with the
        # ``#>> '{}'`` empty-path text operator. Branch on the ACTUAL connection
        # (not the ambient backend selector) so a genuine SQLite connection still
        # emits the SQLite form.
        if _table_exists(conn, "project_capabilities"):
            if connection_is_postgres(conn):
                env_query = (
                    "SELECT je #>> '{}' AS value FROM project_capabilities pc, "
                    "jsonb_array_elements(NULLIF(pc.settings, '')::jsonb #> '{environments}') je "
                    f"WHERE pc.project_id={p} AND pc.type='deployment_environments' "
                    "ORDER BY je #>> '{}'"
                )
            else:
                env_query = (
                    f"SELECT je.value FROM project_capabilities pc, "
                    f"json_each({json_get('pc.settings', '$.environments')}) je "
                    f"WHERE pc.project_id={p} AND pc.type='deployment_environments' "
                    f"ORDER BY je.value"
                )
            rows = query_rows(conn, env_query, (ident.id,))
            if rows:
                return "\n".join(str(r["value"]) for r in rows)

        return None
    finally:
        conn.close()

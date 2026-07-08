"""DB-backed settings snapshot for the project renderer."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, Iterable, Mapping

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.project_identity import resolve_project


@dataclass(frozen=True)
class RendererEnvironmentSettings:
    """One environment row plus its structured settings."""

    id: str
    name: str
    settings: Dict[str, Any]


@dataclass(frozen=True)
class ProjectRendererSettings:
    """DB snapshot used by renderer value collection."""

    project: str
    # The stable namespace every deployed AWS resource is named under
    # (``sites.settings.deploy_namespace``). Deliberately NOT the control-plane
    # project slug: which project record orchestrates a deploy can change
    # (re-parenting the site to another project), but the physical resources —
    # Aurora cluster, S3 buckets, log groups, IAM roles — cannot be renamed
    # without destroy-and-recreate, so their names must derive from this fixed
    # value, not from ``project``.
    deploy_namespace: str
    display_name: str
    site_id: str
    site_settings: Dict[str, Any]
    primary_environment: RendererEnvironmentSettings | None
    environments: tuple[RendererEnvironmentSettings, ...]
    capabilities: Dict[str, Dict[str, Any]]


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _table_exists(conn: Any, table: str) -> bool:
    if db_backend.connection_is_postgres(conn):
        row = conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()
        return bool(row and row[0])
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _column_exists(conn: Any, table: str, column: str) -> bool:
    if db_backend.connection_is_postgres(conn):
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s",
            (table, column),
        ).fetchone()
        return row is not None
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _row_value(row: Any, key: str, index: int) -> Any:
    if row is None:
        return None
    if isinstance(row, Mapping):
        return row.get(key)
    getter = getattr(row, "get", None)
    if getter is not None:
        try:
            return getter(key)
        except (KeyError, TypeError):
            pass
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return row[index]


def _settings_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _stringify(value: Any, default: str = "") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _first_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return dict(item)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _environment_sort_key(env: RendererEnvironmentSettings) -> tuple[int, str]:
    order = {
        "production": 0,
        "prod": 0,
        "stage": 1,
        "staging": 1,
        "local": 9,
    }
    return (order.get(env.name, 5), env.id)


def _site_rows(conn: Any, project_id: int) -> list[Any]:
    if not _table_exists(conn, "sites"):
        return []
    p = _placeholder(conn)
    settings_expr = "settings" if _column_exists(conn, "sites", "settings") else "'{}'"
    return list(
        conn.execute(
            f"SELECT id, name, {settings_expr} AS settings "
            f"FROM sites WHERE project_id={p} ORDER BY id",
            (project_id,),
        ).fetchall()
    )


def _environment_rows(conn: Any, site_ids: Iterable[str]) -> list[Any]:
    site_ids = tuple(site_ids)
    if not site_ids or not _table_exists(conn, "environments"):
        return []
    p = _placeholder(conn)
    placeholders = ", ".join(p for _ in site_ids)
    settings_expr = (
        "settings" if _column_exists(conn, "environments", "settings") else "'{}'"
    )
    return list(
        conn.execute(
            f"SELECT id, name, {settings_expr} AS settings "
            f"FROM environments WHERE site IN ({placeholders}) ORDER BY id",
            site_ids,
        ).fetchall()
    )


def _capability_settings(conn: Any, project_id: int) -> Dict[str, Dict[str, Any]]:
    if not _table_exists(conn, "project_capabilities"):
        return {}
    p = _placeholder(conn)
    settings_expr = (
        "settings"
        if _column_exists(conn, "project_capabilities", "settings")
        else "'{}'"
    )
    rows = conn.execute(
        f"SELECT type, {settings_expr} AS settings "
        f"FROM project_capabilities WHERE project_id={p}",
        (project_id,),
    ).fetchall()
    return {
        str(_row_value(row, "type", 0)): _settings_dict(_row_value(row, "settings", 1))
        for row in rows
    }


def load_project_renderer_settings(project: str) -> ProjectRendererSettings:
    """Load the DB-backed renderer settings snapshot for *project*."""
    conn = db_helpers.connect()
    try:
        return _load_project_renderer_settings(conn, project)
    finally:
        conn.close()


def _load_project_renderer_settings(
    conn: Any, project: str,
) -> ProjectRendererSettings:
    p = _placeholder(conn)
    display_name = project
    ident = resolve_project(conn, project)
    assert ident is not None
    if _table_exists(conn, "projects"):
        row = conn.execute(
            f"SELECT id, name FROM projects WHERE id={p}",
            (ident.id,),
        ).fetchone()
        if row is not None:
            display_name = _stringify(_row_value(row, "name", 1), ident.slug)

    site_rows = _site_rows(conn, ident.id)
    site_row = next(
        (
            row for row in site_rows
            if _settings_dict(_row_value(row, "settings", 2)).get("domains")
        ),
        site_rows[0] if site_rows else None,
    )
    site_id = _stringify(_row_value(site_row, "id", 0), "")
    site_settings = _settings_dict(_row_value(site_row, "settings", 2))

    environments = tuple(
        sorted(
            (
                RendererEnvironmentSettings(
                    id=_stringify(_row_value(row, "id", 0)),
                    name=_stringify(_row_value(row, "name", 1)),
                    settings=_settings_dict(_row_value(row, "settings", 2)),
                )
                for row in _environment_rows(
                    conn, [_stringify(_row_value(row, "id", 0)) for row in site_rows]
                )
            ),
            key=_environment_sort_key,
        )
    )
    primary_environment = environments[0] if environments else None

    return ProjectRendererSettings(
        project=ident.slug,
        # Defaults to the project slug — resources are named after the project
        # unless a site explicitly overrides it (the rare case where the deploy
        # is owned by a project whose name differs from its resource namespace).
        deploy_namespace=_stringify(site_settings.get("deploy_namespace"), ident.slug),
        display_name=display_name,
        site_id=site_id,
        site_settings=site_settings,
        primary_environment=primary_environment,
        environments=environments,
        capabilities=_capability_settings(conn, ident.id),
    )


def primary_domain(settings: ProjectRendererSettings) -> Dict[str, Any]:
    """Return the primary site domain settings object."""
    return _first_mapping(settings.site_settings.get("domains"))


def primary_environment_settings(
    settings: ProjectRendererSettings,
) -> Dict[str, Any]:
    """Return primary environment settings, or an empty mapping."""
    if settings.primary_environment is None:
        return {}
    return settings.primary_environment.settings


def primary_server(settings: ProjectRendererSettings) -> Dict[str, Any]:
    """Return the primary server settings object."""
    return _first_mapping(primary_environment_settings(settings).get("servers"))


def project_primary_domain_name(project: str) -> str:
    """Return the project's primary domain name from DB-backed site settings."""

    settings = load_project_renderer_settings(project)
    return _stringify(primary_domain(settings).get("domain_name"))


def project_ci_workflow_file(project: str) -> str:
    """Return the project's CI workflow file from capability settings."""

    settings = load_project_renderer_settings(project)
    ci_settings = settings.capabilities.get("ci_workflow_file", {})
    return _stringify(ci_settings.get("workflow_file"))

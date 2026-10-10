"""Locked rows and capability creation for Pulumi state migration."""

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.pulumi_state_capability import CAPABILITY_TYPE


def _locked_site_row(conn: Any, project_id: int, site: str) -> Any:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    return conn.execute(
        "SELECT id, COALESCE(settings, '{}') FROM sites "
        f"WHERE project_id=%s AND name=%s{suffix}",
        (project_id, site),
    ).fetchone()


def _ensure_capability_row(conn: Any, project_id: int) -> bool:
    cursor = conn.execute(
        "INSERT INTO project_capabilities "
        "(project_id, type, settings, created_at) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT(project_id, type) DO NOTHING",
        (project_id, CAPABILITY_TYPE, "{}", instant_parameter(conn, utc_now())),
    )
    return cursor.rowcount == 1


def _locked_capability_row(conn: Any, project_id: int) -> Any:
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    return conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id=%s AND type=%s{suffix}",
        (project_id, CAPABILITY_TYPE),
    ).fetchone()

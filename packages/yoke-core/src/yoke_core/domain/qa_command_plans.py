"""Read project commands from their QA-plan contracts."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.project_identity import resolve_project


REGISTERED_SCOPES: Tuple[str, ...] = ("quick", "full", "e2e", "smoke")


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _command(raw: Any) -> str:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return ""
    command = value.get("command") if isinstance(value, dict) else None
    return str(command).strip() if isinstance(command, str) else ""


def list_registered_commands_for_project_id(
    conn: Any, project_id: int,
) -> Dict[str, str]:
    """Return migrated scope commands in stable scope order."""
    marker = _placeholder(conn)
    rows = query_rows(
        conn,
        "SELECT p.slug, c.method_config FROM qa_plans p "
        "JOIN qa_plan_cases c ON c.plan_id=p.id "
        f"WHERE p.project_id={marker} AND p.retired_at IS NULL "
        "AND substr(p.slug, 1, 19)='registered-command-' "
        "AND c.method_id='command' ORDER BY p.slug, c.position",
        (int(project_id),),
    )
    found: Dict[str, str] = {}
    for row in rows:
        scope = str(row["slug"]).removeprefix("registered-command-")
        command = _command(row["method_config"])
        if scope in REGISTERED_SCOPES and command:
            found[scope] = command
    return {
        scope: found[scope]
        for scope in REGISTERED_SCOPES
        if scope in found
    }


def list_registered_commands(
    project: str, db_path: Optional[str] = None,
) -> Dict[str, str]:
    """Return the project's migrated Command-plan commands."""
    conn = connect(db_path)
    try:
        identity = resolve_project(conn, project, required=False)
        if identity is None:
            return {}
        return list_registered_commands_for_project_id(conn, int(identity.id))
    finally:
        conn.close()


def get_registered_command(
    project: str,
    scope: str,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Return one migrated scope command, or ``None`` when absent."""
    if scope not in REGISTERED_SCOPES:
        raise ValueError(
            f"unknown registered command scope {scope!r}; expected one of "
            + ", ".join(REGISTERED_SCOPES)
        )
    return list_registered_commands(project, db_path=db_path).get(scope)


__all__ = [
    "REGISTERED_SCOPES",
    "get_registered_command",
    "list_registered_commands",
    "list_registered_commands_for_project_id",
]

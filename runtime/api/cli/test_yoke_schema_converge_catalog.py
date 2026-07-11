"""Role-catalog coverage for the source-dev schema convergence command."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_cli.commands.schema_converge import schema_converge
from yoke_core.domain.actor_permissions import (
    ROLE_DEPLOYMENT_CI,
    ROLE_INFRASTRUCTURE_CI,
    ROLE_PERMISSION_KEYS,
)


_CI_ROLES = (ROLE_DEPLOYMENT_CI, ROLE_INFRASTRUCTURE_CI)


def _permission_keys(conn, role_name: str) -> set[str]:
    rows = conn.execute(
        "SELECT p.key FROM permissions p "
        "JOIN role_permissions rp ON rp.permission_id = p.id "
        "JOIN roles r ON r.id = rp.role_id "
        "WHERE r.name = %s",
        (role_name,),
    ).fetchall()
    return {str(row["key"] if isinstance(row, dict) else row[0]) for row in rows}


def _drop_ci_roles(conn) -> None:
    for role_name in _CI_ROLES:
        conn.execute(
            "DELETE FROM role_permissions WHERE role_id = "
            "(SELECT id FROM roles WHERE name = %s)",
            (role_name,),
        )
        conn.execute("DELETE FROM roles WHERE name = %s", (role_name,))
    conn.commit()


def test_schema_converge_restores_ci_roles_and_permissions(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """The operator command heals catalog drift and remains idempotent."""
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.delenv("YOKE_PG_DSN_FILE", raising=False)
    monkeypatch.delenv("YOKE_DB_SECRET_ARN", raising=False)

    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            _drop_ci_roles(conn)
            assert all(not _permission_keys(conn, role) for role in _CI_ROLES)

            assert schema_converge(["--json"]) == 0
            first = json.loads(capsys.readouterr().out)
            assert first["catalog"] == "roles_permissions"
            for role_name in _CI_ROLES:
                assert _permission_keys(conn, role_name) == set(
                    ROLE_PERMISSION_KEYS[role_name]
                )

            assert schema_converge(["--json"]) == 0
            capsys.readouterr()
            for role_name in _CI_ROLES:
                row = conn.execute(
                    "SELECT COUNT(*) FROM roles WHERE name = %s",
                    (role_name,),
                ).fetchone()
                assert row is not None
                count = row["count"] if isinstance(row, dict) else row[0]
                assert count == 1
        finally:
            conn.close()

"""Flow schema boot leaves project delivery topology to the project."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.flow_init import cmd_init as flow_cmd_init


def test_schema_init_does_not_seed_project_delivery_topology(
    tmp_path: Path,
) -> None:
    from runtime.api.fixtures.file_test_db import init_test_db
    from yoke_core.domain import db_backend

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS projects ("
                "id BIGINT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, "
                "created_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS items (id BIGINT PRIMARY KEY, status TEXT)"
            )
            conn.execute("INSERT INTO projects (id, slug) VALUES (41, 'yoke')")
            conn.execute("INSERT INTO projects (id, slug) VALUES (43, 'platform')")
            conn.commit()
        finally:
            conn.close()

    with init_test_db(tmp_path, apply_schema=_apply):
        conn = db_backend.connect()
        try:
            flow_cmd_init(conn)
            count = conn.execute("SELECT COUNT(*) FROM deployment_flows").fetchone()[0]
            assert int(count) == 0
        finally:
            conn.close()

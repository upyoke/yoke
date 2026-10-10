"""Flow schema boot leaves project delivery topology to the project."""

from __future__ import annotations

from pathlib import Path

import pytest

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
                "created_at TIMESTAMPTZ)"
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


@pytest.mark.parametrize("schema_owner", ["flows", "runs"])
def test_missing_deployment_clock_columns_converge_as_native_instants(
    tmp_path, schema_owner
):
    from runtime.api.fixtures.file_test_db import init_test_db
    from yoke_contracts.timestamps import parse_instant
    from yoke_core.domain import db_backend, deployment_runs_schema_init

    stamp = parse_instant("2026-10-08T22:15:00.123456+05:45")
    clocks = ("current_stage_entered_at", "composition_frozen_at", "settling_at")

    def apply_schema():
        with db_backend.connect() as conn:
            conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, status TEXT)")
            conn.execute("INSERT INTO projects VALUES (41, 'fixture')")
            flow_cmd_init(conn)
        deployment_runs_schema_init.cmd_init()

    with init_test_db(tmp_path, apply_schema=apply_schema):
        with db_backend.connect() as conn:
            conn.execute("SET TIME ZONE 'Asia/Kathmandu'")
            conn.execute(
                "INSERT INTO deployment_flows (id, project_id, name, stages, created_at) "
                "VALUES ('fixture', 41, 'Fixture', '[]', %s)",
                (stamp,),
            )
            conn.execute(
                "INSERT INTO deployment_runs "
                "(id, project_id, flow, created_at, artifact_identity) "
                "VALUES ('run-existing', 41, 'fixture', %s, 'opaque-artifact')",
                (stamp,),
            )
            # A managed disposable database models a pre-existing universe
            # missing additive clock columns, rather than another fresh birth.
            for column in clocks:
                conn.execute(f"ALTER TABLE deployment_runs DROP COLUMN {column}")
            conn.commit()
            for _ in range(2):
                if schema_owner == "flows":
                    flow_cmd_init(conn)
                else:
                    deployment_runs_schema_init.cmd_init()
            kinds = dict(
                conn.execute(
                    "SELECT column_name, udt_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='deployment_runs'"
                ).fetchall()
            )
            assert {column: kinds[column] for column in clocks} == {
                column: "timestamptz" for column in clocks
            }
            assert kinds["artifact_identity"] == "text"
            row = conn.execute(
                "SELECT created_at, artifact_identity, current_stage_entered_at, "
                "composition_frozen_at, settling_at FROM deployment_runs "
                "WHERE id='run-existing'"
            ).fetchone()
            assert tuple(row) == (stamp, "opaque-artifact", None, None, None)
            conn.execute(
                "UPDATE deployment_runs SET current_stage_entered_at=%s, "
                "composition_frozen_at=%s, settling_at=%s WHERE id='run-existing'",
                (stamp, stamp, stamp),
            )
            assert tuple(
                conn.execute(
                    "SELECT current_stage_entered_at, composition_frozen_at, settling_at "
                    "FROM deployment_runs WHERE id='run-existing'"
                ).fetchone()
            ) == (stamp, stamp, stamp)

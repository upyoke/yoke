"""Project-boundary coverage for deployment-flow repointing."""

import json

import pytest

from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.flow import cmd_create, cmd_delete


def _insert_projects(conn):
    created_at = "2026-04-20T00:00:00Z"
    for project_id, slug, name in (
        (1, "yoke", "Yoke"),
        (2, "externalwebapp", "ExternalWebapp"),
    ):
        conn.execute(
            "INSERT INTO projects (id, slug, name, "
            "public_item_prefix, created_at) "
            "VALUES (%s, %s, %s, 'YOK', %s) "
            "ON CONFLICT(id) DO NOTHING",
            (project_id, slug, name, created_at),
        )
    conn.commit()


def test_delete_refuses_cross_project_repoint(test_db):
    _insert_projects(test_db)
    stages = json.dumps([{"name": "s1", "executor": "auto"}])
    cmd_create(test_db, "f-yoke-old", "yoke", "YokeOld", "D", stages)
    cmd_create(
        test_db,
        "f-external-new",
        "externalwebapp",
        "ExternalNew",
        "D",
        stages,
    )
    test_db.execute(
        "INSERT INTO items ("
        "id, project_id, project_sequence, workflow_id, "
        "workflow_version_id, title, status, deployment_flow, "
        "created_at, updated_at"
        ") VALUES ("
        "9003, 1, 9003, 'issue', "
        "(SELECT current_version_id FROM workflows WHERE id='issue'), "
        "'T', 'done', 'f-yoke-old', "
        "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z'"
        ")"
    )
    test_db.commit()

    with pytest.raises(ValueError, match="deleted flow's project"):
        cmd_delete(test_db, "f-yoke-old", "f-external-new")

    assert (
        query_scalar(
            test_db,
            "SELECT deployment_flow FROM items WHERE id=9003",
        )
        == "f-yoke-old"
    )
    assert (
        query_scalar(
            test_db,
            "SELECT COUNT(*) FROM deployment_flows WHERE id='f-yoke-old'",
        )
        == 1
    )

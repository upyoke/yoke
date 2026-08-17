"""Prospective project/deployment-flow binding tests for item PATCH."""

from __future__ import annotations

import threading

import pytest

from runtime.api.api_items_test_helpers import (
    make_client_fixture,
    make_test_db_fixture,
)
from runtime.api.fixtures.file_test_db import connect_test_db


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


def _clone_flow_for_project(conn, flow_id: str, project: str) -> None:
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, description, stages, on_failure, "
        "created_at, target_tier, target_environment_id, "
        "done_description, status) "
        "SELECT %s, (SELECT id FROM projects WHERE slug=%s), %s, "
        "description, stages, on_failure, created_at, target_tier, "
        "target_environment_id, done_description, status "
        "FROM deployment_flows WHERE id='test-approval-flow'",
        (flow_id, project, flow_id),
    )
    conn.commit()


def test_project_only_patch_rejects_existing_flow_project_mismatch(client, test_db):
    assigned = client.patch(
        "/v1/items/1",
        json={"deployment_flow": "test-approval-flow"},
    )
    assert assigned.status_code == 200

    response = client.patch(
        "/v1/items/1",
        json={"project": "externalwebapp"},
    )

    assert response.status_code == 422
    assert "prospective item project" in response.json()["error"]["message"]
    conn = connect_test_db(test_db["db_path"])
    row = conn.execute(
        "SELECT p.slug, i.deployment_flow FROM items i "
        "JOIN projects p ON p.id=i.project_id WHERE i.id=1"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("yoke", "test-approval-flow")


def test_combined_project_and_flow_patch_validates_final_pair(client, test_db):
    conn = connect_test_db(test_db["db_path"])
    _clone_flow_for_project(conn, "external-approval-flow", "externalwebapp")
    conn.close()

    response = client.patch(
        "/v1/items/1",
        json={
            "project": "externalwebapp",
            "deployment_flow": "external-approval-flow",
        },
    )

    assert response.status_code == 200
    assert response.json()["project"] == "externalwebapp"
    assert response.json()["deployment_flow"] == "external-approval-flow"


def test_combined_project_and_flow_patch_rejects_mismatched_pair(client, test_db):
    response = client.patch(
        "/v1/items/1",
        json={
            "project": "externalwebapp",
            "deployment_flow": "test-approval-flow",
        },
    )

    assert response.status_code == 422
    assert "prospective item project" in response.json()["error"]["message"]
    conn = connect_test_db(test_db["db_path"])
    row = conn.execute(
        "SELECT p.slug, i.deployment_flow FROM items i "
        "JOIN projects p ON p.id=i.project_id WHERE i.id=1"
    ).fetchone()
    conn.close()
    assert tuple(row) == ("yoke", None)


def test_explicit_empty_project_validates_the_writer_default(client, test_db):
    conn = connect_test_db(test_db["db_path"])
    _clone_flow_for_project(conn, "external-empty-project-flow", "externalwebapp")
    conn.close()
    assigned = client.patch(
        "/v1/items/1",
        json={
            "project": "externalwebapp",
            "deployment_flow": "external-empty-project-flow",
        },
    )
    assert assigned.status_code == 200

    response = client.patch(
        "/v1/items/1",
        json={"project": ""},
    )

    assert response.status_code == 422
    assert "prospective item project is 'yoke'" in (response.json()["error"]["message"])
    conn = connect_test_db(test_db["db_path"])
    row = conn.execute(
        "SELECT p.slug, i.deployment_flow FROM items i "
        "JOIN projects p ON p.id=i.project_id WHERE i.id=1"
    ).fetchone()
    conn.close()
    assert tuple(row) == (
        "externalwebapp",
        "external-empty-project-flow",
    )


def test_explicit_empty_project_and_default_project_flow_succeed(client, test_db):
    moved = client.patch(
        "/v1/items/1",
        json={"project": "externalwebapp"},
    )
    assert moved.status_code == 200

    response = client.patch(
        "/v1/items/1",
        json={
            "project": "",
            "deployment_flow": "test-approval-flow",
        },
    )

    assert response.status_code == 200
    assert response.json()["project"] == "yoke"
    assert response.json()["deployment_flow"] == "test-approval-flow"


def test_project_only_patch_locks_the_existing_flow(client, test_db, monkeypatch):
    from runtime.api.fixtures.pg_testdb import connect_test_database
    from yoke_core.api.routes import items_write
    from yoke_core.domain.flow_crud import cmd_delete

    conn = connect_test_db(test_db["db_path"])
    _clone_flow_for_project(conn, "project-lock-flow", "yoke")
    conn.close()
    assigned = client.patch(
        "/v1/items/1",
        json={"deployment_flow": "project-lock-flow"},
    )
    assert assigned.status_code == 200
    conn = connect_test_db(test_db["db_path"])
    delete_conn = connect_test_database(str(conn.info.dbname))
    conn.close()
    patch_ready = threading.Event()
    release_patch = threading.Event()
    delete_done = threading.Event()
    outcome = {}
    original_prepare = items_write.prepare_update

    def pause_before_write(*args, **kwargs):
        if kwargs.get("field_name") == "project":
            patch_ready.set()
            assert release_patch.wait(timeout=10)
        return original_prepare(*args, **kwargs)

    def patch_project():
        outcome["response"] = client.patch(
            "/v1/items/1",
            json={"project": "yoke"},
        )

    def delete_flow():
        try:
            outcome["delete"] = cmd_delete(delete_conn, "project-lock-flow")
        except Exception as exc:
            outcome["delete_error"] = exc
        finally:
            delete_done.set()

    monkeypatch.setattr(items_write, "prepare_update", pause_before_write)
    patch_worker = threading.Thread(target=patch_project)
    delete_worker = threading.Thread(target=delete_flow)
    try:
        patch_worker.start()
        assert patch_ready.wait(timeout=10)
        delete_worker.start()
        assert not delete_done.wait(timeout=0.2)
        release_patch.set()
        patch_worker.join(timeout=10)
        delete_worker.join(timeout=10)
    finally:
        release_patch.set()
        delete_conn.close()

    assert not patch_worker.is_alive()
    assert not delete_worker.is_alive()
    assert outcome["response"].status_code == 200
    assert isinstance(outcome["delete_error"], ValueError)
    assert "still reference" in str(outcome["delete_error"])

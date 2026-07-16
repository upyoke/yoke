"""HTTPS contracts for project-owned environment settings CAS mutation."""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.fixtures.file_test_db import connect_test_db


@pytest.fixture()
def environment_db():
    fixture = make_test_db_fixture()
    db = next(fixture)
    conn = connect_test_db(db["db_path"])
    try:
        conn.execute(
            "CREATE TABLE sites (id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, "
            "name TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE environments (id TEXT PRIMARY KEY, site TEXT NOT NULL, "
            "name TEXT NOT NULL, settings TEXT DEFAULT '{}', "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO sites (id, project_id, name, created_at) "
            "VALUES ('yoke-api', 1, 'Yoke API', '2026-01-01T00:00:00Z'), "
            "('buzz-api', 2, 'Buzz API', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO environments (id, site, name, settings, created_at) "
            "VALUES ('yoke-api-prod', 'yoke-api', 'prod', "
            "'{\"pulumi\":{\"activation_state\":\"active\"},\"servers\":[{\"key\":\"old\"}]}', "
            "'2026-01-01T00:00:00Z'), "
            "('buzz-api-prod', 'buzz-api', 'prod', '{}', "
            "'2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()
    try:
        yield db
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass


@pytest.fixture()
def client(environment_db):
    with _client_for_db(environment_db["db_path"]) as authed:
        yield authed


def _call(client, function: str, payload: dict):
    return client.post(
        "/v1/functions/call",
        json={
            "function": function,
            "version": "v1",
            "actor": {"actor_id": "test", "session_id": ""},
            "target": {"kind": "global"},
            "payload": payload,
            "preconditions": {},
            "options": {},
        },
    )


def test_https_merge_retires_environment_and_returns_canonical_document(client):
    response = _call(
        client,
        "projects.environment_settings.merge",
        {
            "project": "yoke",
            "environment_id": "yoke-api-prod",
            "assignments": {
                "pulumi.activation_state": "render_only",
                "servers": [],
            },
        },
    )
    assert response.status_code == 200
    stored = json.loads(response.json()["result"]["settings_json"])
    assert stored["pulumi"]["activation_state"] == "render_only"
    assert stored["servers"] == []


def test_https_refuses_project_environment_mismatch(client):
    response = _call(
        client,
        "projects.environment_settings.get",
        {"project": "yoke", "environment_id": "buzz-api-prod"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "project_mismatch"

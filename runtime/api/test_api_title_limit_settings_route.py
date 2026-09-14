"""HTTPS save of the ``title_max_length`` project-policy setting.

A rejected save must never partially land: the stored document after a
refused merge is byte-identical to the document before it.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.project_identity import resolve_project_id


@pytest.fixture()
def title_limit_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(title_limit_db):
    with _client_for_db(title_limit_db["db_path"]) as authed:
        yield authed


def _merge(client, value) -> object:
    return client.post(
        "/v1/functions/call",
        json={
            "function": "projects.capability_settings.merge",
            "version": "v1",
            "actor": {"actor_id": "test", "session_id": ""},
            "target": {"kind": "global"},
            "payload": {
                "project": "yoke",
                "cap_type": "project-policy",
                "assignments": {"title_max_length": value},
            },
            "preconditions": {},
            "options": {},
        },
    )


def _stored_title_limit(db_path: str) -> object:
    conn = connect_test_db(db_path)
    try:
        row = conn.execute(
            "SELECT settings FROM project_capabilities "
            "WHERE project_id=%s AND type='project-policy'",
            (resolve_project_id(conn, "yoke"),),
        ).fetchone()
    finally:
        conn.close()
    settings = {} if row is None else json.loads(row["settings"])
    return settings.get("title_max_length")


def test_a_non_integral_save_is_rejected_without_mutating_the_stored_value(
    client,
    title_limit_db,
):
    accepted = _merge(client, 55)
    assert accepted.status_code == 200

    rejected = _merge(client, 10.5)

    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "validation_error"
    assert _stored_title_limit(title_limit_db["db_path"]) == 55

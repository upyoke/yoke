"""HTTPS contracts for project capability settings read/CAS mutation."""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.actor_permissions import ROLE_OWNER, grant_actor_project_role
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.project_identity import resolve_project_id


@pytest.fixture()
def capability_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(capability_db):
    with _client_for_db(capability_db["db_path"]) as authed:
        yield authed


def _call(
    client,
    function: str,
    payload: dict,
    *,
    target_project: str | None = None,
    headers: dict[str, str] | None = None,
):
    target = {"kind": "global"}
    if target_project is not None:
        target["project_id"] = target_project
    return client.post(
        "/v1/functions/call",
        json={
            "function": function,
            "version": "v1",
            "actor": {"actor_id": "test", "session_id": ""},
            "target": target,
            "payload": payload,
            "preconditions": {},
            "options": {},
        },
        headers=headers,
    )


def _project_owner_headers(db_path: str, project: str) -> dict[str, str]:
    conn = connect_test_db(db_path)
    try:
        actor_id = seed_human_actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=resolve_project_id(conn, project),
            role_name=ROLE_OWNER,
            granted_by_actor_id=actor_id,
        )
        token = mint_token(
            conn,
            actor_id=actor_id,
            name=f"capability-settings-owner-{project}",
        )
        conn.commit()
    finally:
        conn.close()
    return {"Authorization": f"Bearer {token.raw_token}"}


def _set(client, settings_json: str, **extra):
    payload = {
        "project": "yoke",
        "cap_type": "docker",
        "settings_json": settings_json,
        **extra,
    }
    return _call(client, "projects.capability_settings.set", payload)


def _get(client, cap_type: str = "docker"):
    return _call(
        client,
        "projects.capability_settings.get",
        {"project": "yoke", "cap_type": cap_type},
    )


def test_https_create_get_and_stale_base_refusal(client):
    created = _set(client, '{"host":"original"}', create=True)
    assert created.status_code == 200
    base = created.json()["result"]["settings_json"]

    updated = _set(client, '{"host":"current"}', base_settings_json=base)
    assert updated.status_code == 200

    stale = _set(client, '{"host":"clobber"}', base_settings_json=base)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "settings_conflict"
    assert json.loads(_get(client).json()["result"]["settings_json"]) == {
        "host": "current"
    }


def test_https_merges_compose_independent_paths(client):
    first = _call(
        client,
        "projects.capability_settings.merge",
        {
            "project": "yoke",
            "cap_type": "docker",
            "assignments": {"registry": "ecr"},
        },
    )
    assert first.status_code == 200
    second = _call(
        client,
        "projects.capability_settings.merge",
        {
            "project": "yoke",
            "cap_type": "docker",
            "assignments": {"deploy.auto_on_push": True},
        },
    )
    assert second.status_code == 200
    assert json.loads(second.json()["result"]["settings_json"]) == {
        "registry": "ecr",
        "deploy": {"auto_on_push": True},
    }


def test_https_runner_fleet_settings_preserve_typed_app_authority(client):
    settings = {
        "repo": "upyoke/platform",
        "github_app": {
            "issuer": " Iv1.runner-fleet ",
            "api_url": "https://api.github.com/",
            "private_key_secret_arn": (
                "arn:aws:secretsmanager:us-east-1:123456789012:"
                "secret:yoke-github-app-AbCdEf"
            ),
        },
        "desired_runner_count": 1,
        "max_runner_count": 1,
    }
    response = _call(
        client,
        "projects.capability_settings.set",
        {
            "project": "yoke",
            "cap_type": "github-actions-runner-fleet",
            "settings_json": json.dumps(settings),
            "create": True,
        },
    )
    assert response.status_code == 200
    stored = json.loads(response.json()["result"]["settings_json"])
    assert stored["github_app"]["issuer"] == "Iv1.runner-fleet"
    assert stored["github_app"]["api_url"] == "https://api.github.com"


@pytest.mark.parametrize(
    "settings",
    [
        {"desired_runner_count": 2, "max_runner_count": 4},
        {"unknown_selector": "must-refuse"},
    ],
)
def test_https_runner_fleet_invalid_or_unknown_fields_refuse_without_mutation(
    client,
    settings,
):
    response = _call(
        client,
        "projects.capability_settings.set",
        {
            "project": "yoke",
            "cap_type": "github-actions-runner-fleet",
            "settings_json": json.dumps(settings),
            "create": True,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert _get(client, "github-actions-runner-fleet").status_code == 404


def test_https_unknown_request_field_is_refused(client):
    response = _call(
        client,
        "projects.capability_settings.set",
        {
            "project": "yoke",
            "cap_type": "docker",
            "settings_json": "{}",
            "create": True,
            "unexpected": "must-refuse",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"invalid_payload", "payload_invalid"}
    assert _get(client).status_code == 404


def test_https_github_full_document_write_remains_binding_owned(client):
    response = _call(
        client,
        "projects.capability_settings.set",
        {
            "project": "yoke",
            "cap_type": "github",
            "settings_json": "{}",
            "create": True,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "binding-owned" in body["error"]["message"]


def test_https_read_target_cannot_override_payload_project(
    client,
    capability_db,
):
    conn = connect_test_db(capability_db["db_path"])
    try:
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) "
            "VALUES (%s, 'docker', '{\"host\":\"buzz-private\"}', "
            "'2026-01-01T00:00:00Z')",
            (resolve_project_id(conn, "buzz"),),
        )
        conn.commit()
    finally:
        conn.close()
    headers = _project_owner_headers(capability_db["db_path"], "yoke")

    response = _call(
        client,
        "projects.capability_settings.get",
        {"project": "buzz", "cap_type": "docker"},
        target_project="yoke",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


@pytest.mark.parametrize(
    ("function_id", "payload"),
    [
        (
            "projects.capability_settings.set",
            {
                "project": "buzz",
                "cap_type": "docker",
                "settings_json": '{"host":"must-not-land"}',
                "create": True,
            },
        ),
        (
            "projects.capability_settings.merge",
            {
                "project": "buzz",
                "cap_type": "docker",
                "assignments": {"host": "must-not-land"},
            },
        ),
    ],
)
def test_https_mutation_target_cannot_override_payload_project(
    client,
    capability_db,
    function_id,
    payload,
):
    headers = _project_owner_headers(capability_db["db_path"], "yoke")

    response = _call(
        client,
        function_id,
        payload,
        target_project="yoke",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    conn = connect_test_db(capability_db["db_path"])
    try:
        row = conn.execute(
            "SELECT settings FROM project_capabilities "
            "WHERE project_id=%s AND type='docker'",
            (resolve_project_id(conn, "buzz"),),
        ).fetchone()
    finally:
        conn.close()
    assert row is None

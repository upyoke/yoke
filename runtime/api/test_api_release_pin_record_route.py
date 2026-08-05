"""Capability-routed release-pin mutation and token authorization contracts."""

from __future__ import annotations

import json

import pytest

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.actor_permissions import (
    ROLE_DEPLOYMENT_CI,
    ROLE_INFRASTRUCTURE_CI,
    grant_actor_project_role,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.projects_capabilities_settings import (
    cmd_capability_merge_settings,
)


@pytest.fixture()
def release_pin_db():
    fixture = make_test_db_fixture()
    db = next(fixture)
    with connect_test_db(db["db_path"]) as conn:
        conn.execute(
            "CREATE TABLE sites (id TEXT PRIMARY KEY, project_id INTEGER NOT "
            "NULL, name TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE environments (id TEXT PRIMARY KEY, site TEXT NOT "
            "NULL, name TEXT NOT NULL, settings TEXT DEFAULT '{}', "
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO sites (id, project_id, name, created_at) VALUES "
            "('primary-api', 1, 'Primary API', '2026-01-01T00:00:00Z'), "
            "('external-api', 2, 'External API', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO environments (id, site, name, settings, created_at) "
            "VALUES ('primary-stage', 'primary-api', 'stage', %s, "
            "'2026-01-01T00:00:00Z'), "
            "('external-stage', 'external-api', 'stage', '{}', "
            "'2026-01-01T00:00:00Z')",
            (
                json.dumps(
                    {
                        "delivery": {"engine_version": "old"},
                        "release": {"yoke_pin": "untouched"},
                        "unrelated": True,
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) VALUES (1, 'release_pin', "
            "%s, '2026-01-01T00:00:00Z')",
            (
                json.dumps(
                    {
                        "environment_by_target": {"stage": "primary-stage"},
                        "desired_pin_path": "delivery.engine_version",
                    }
                ),
            ),
        )
        conn.commit()
    try:
        yield db
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass


@pytest.fixture()
def client(release_pin_db):
    with _client_for_db(release_pin_db["db_path"]) as authed:
        yield authed


def _envelope(
    *,
    project: str = "yoke",
    environment: str = "stage",
    pin: str = "0.1.1+launch.188",
) -> dict:
    return {
        "function": "release_pin.record",
        "version": "v1",
        "actor": {"actor_id": "test", "session_id": "release-pin-test"},
        "target": {"kind": "global", "project_id": project},
        "payload": {
            "project": project,
            "environment": environment,
            "pin": pin,
        },
        "preconditions": {},
        "options": {},
    }


def _stored_settings(db_path: str, environment_id: str = "primary-stage") -> dict:
    with connect_test_db(db_path) as conn:
        raw = conn.execute(
            "SELECT settings FROM environments WHERE id=%s", (environment_id,)
        ).fetchone()[0]
    return json.loads(str(raw))


def _set_capability(db_path: str, settings: dict) -> None:
    with connect_test_db(db_path) as conn:
        conn.execute(
            "UPDATE project_capabilities SET settings=%s "
            "WHERE project_id=1 AND type='release_pin'",
            (json.dumps(settings),),
        )
        conn.commit()


def _token_headers(db_path: str, role_name: str, project: str = "yoke") -> dict:
    with connect_test_db(db_path) as conn:
        actor_id = seed_human_actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=resolve_project_id(conn, project),
            role_name=role_name,
            granted_by_actor_id=actor_id,
        )
        token = mint_token(conn, actor_id=actor_id, name=f"test-{role_name}")
        conn.commit()
    return {"Authorization": f"Bearer {token.raw_token}"}


def test_record_mutates_only_the_capability_configured_leaf(client, release_pin_db):
    response = client.post("/v1/functions/call", json=_envelope())

    assert response.status_code == 200
    result = response.json()["result"]
    assert result == {
        "project": "yoke",
        "environment": "stage",
        "environment_id": "primary-stage",
        "settings_path": "delivery.engine_version",
        "pin": "0.1.1+launch.188",
        "changed": True,
    }
    stored = _stored_settings(release_pin_db["db_path"])
    assert stored["delivery"]["engine_version"] == "0.1.1+launch.188"
    assert stored["release"]["yoke_pin"] == "untouched"
    assert stored["unrelated"] is True


def test_record_is_idempotent_when_the_same_pin_is_already_stored(
    client, release_pin_db
):
    assert client.post("/v1/functions/call", json=_envelope()).status_code == 200
    response = client.post("/v1/functions/call", json=_envelope())

    assert response.status_code == 200
    assert response.json()["result"]["changed"] is False


def test_legacy_capability_without_path_fails_closed(client, release_pin_db):
    before = _stored_settings(release_pin_db["db_path"])
    _set_capability(
        release_pin_db["db_path"],
        {"environment_by_target": {"stage": "primary-stage"}},
    )

    response = client.post("/v1/functions/call", json=_envelope())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "capability_invalid"
    assert _stored_settings(release_pin_db["db_path"]) == before


def test_owner_merge_can_explicitly_converge_a_legacy_capability(
    client, release_pin_db
):
    _set_capability(
        release_pin_db["db_path"],
        {"environment_by_target": {"stage": "primary-stage"}},
    )

    cmd_capability_merge_settings(
        "yoke",
        "release_pin",
        {"desired_pin_path": "delivery.engine_version"},
        db_path=release_pin_db["db_path"],
    )
    response = client.post("/v1/functions/call", json=_envelope())

    assert response.status_code == 200
    assert response.json()["result"]["changed"] is True


def test_unconfigured_target_and_cross_project_environment_are_refused(
    client, release_pin_db
):
    unconfigured = client.post(
        "/v1/functions/call", json=_envelope(environment="production")
    )
    assert unconfigured.status_code == 400
    assert unconfigured.json()["error"]["code"] == "target_not_configured"

    _set_capability(
        release_pin_db["db_path"],
        {
            "environment_by_target": {"stage": "external-stage"},
            "desired_pin_path": "delivery.engine_version",
        },
    )
    mismatch = client.post("/v1/functions/call", json=_envelope())
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "project_mismatch"


def test_deployment_ci_can_record_but_cannot_use_generic_settings_mutation(
    client, release_pin_db
):
    headers = _token_headers(
        release_pin_db["db_path"], ROLE_DEPLOYMENT_CI
    )
    recorded = client.post(
        "/v1/functions/call", json=_envelope(), headers=headers
    )
    assert recorded.status_code == 200

    generic_merge = client.post(
        "/v1/functions/call",
        json={
            **_envelope(),
            "function": "projects.environment_settings.merge",
            "payload": {
                "project": "yoke",
                "environment_id": "primary-stage",
                "assignments": {"unrelated": False},
            },
        },
        headers=headers,
    )
    assert generic_merge.status_code == 403
    assert generic_merge.json()["error"]["code"] == "permission_denied"


def test_infrastructure_ci_and_cross_project_deployment_ci_are_denied(
    client, release_pin_db
):
    infrastructure_headers = _token_headers(
        release_pin_db["db_path"], ROLE_INFRASTRUCTURE_CI
    )
    denied_infrastructure = client.post(
        "/v1/functions/call",
        json=_envelope(),
        headers=infrastructure_headers,
    )
    assert denied_infrastructure.status_code == 403

    deployment_headers = _token_headers(
        release_pin_db["db_path"], ROLE_DEPLOYMENT_CI
    )
    denied_cross_project = client.post(
        "/v1/functions/call",
        json=_envelope(project="externalwebapp"),
        headers=deployment_headers,
    )
    assert denied_cross_project.status_code == 403
    assert denied_cross_project.json()["error"]["code"] == "permission_denied"


def test_authorized_target_cannot_mask_a_different_payload_project(
    client, release_pin_db
):
    headers = _token_headers(
        release_pin_db["db_path"], ROLE_DEPLOYMENT_CI
    )
    envelope = _envelope()
    envelope["payload"]["project"] = "externalwebapp"

    response = client.post(
        "/v1/functions/call", json=envelope, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "project_mismatch"

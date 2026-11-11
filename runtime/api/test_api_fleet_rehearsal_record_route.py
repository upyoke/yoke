"""The preflight_executor role reads release settings and records receipts only."""

from __future__ import annotations

import pytest

from runtime.api.api_release_pin_record_route_test_support import (
    _stored_settings as _stored_settings,
    client as client,
    release_pin_db as release_pin_db,
)
from runtime.api.fixtures.actor_roles import seed_project_role, seed_service_actor
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.actor_permissions import (
    PERM_FLEET_REHEARSAL_RECORD,
    PERM_ITEMS_READ,
    ROLE_ADMIN,
    ROLE_DEPLOYMENT_CI,
    ROLE_OWNER,
    ROLE_PERMISSION_KEYS,
    ROLE_PREFLIGHT_EXECUTOR,
)
from yoke_core.domain.actor_role import (
    MACHINE_ONLY_ROLES,
    ActorRoleRefused,
    require_human_org_role,
)
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.fleet_rehearsal_record_permission import (
    is_fleet_rehearsal_merge,
)
from yoke_core.domain.project_identity import resolve_project_id

MERGE = "projects.environment_settings.merge"
RECEIPT_PATH = "release.fleet_rehearsal.yoke.run"


def _headers(db_path: str, project: str = "yoke") -> dict:
    with connect_test_db(db_path) as conn:
        actor_id = seed_service_actor(conn)
        seed_project_role(
            conn,
            actor_id=actor_id,
            project_id=resolve_project_id(conn, project),
            role_name=ROLE_PREFLIGHT_EXECUTOR,
            granted_by_actor_id=actor_id,
        )
        token = mint_token(conn, actor_id=actor_id, name="test-preflight-executor")
        conn.commit()
    return {"Authorization": f"Bearer {token.raw_token}"}


def _call(client, headers, function: str, payload: dict, project: str = "yoke"):
    return client.post(
        "/v1/functions/call",
        json={
            "function": function,
            "version": "v1",
            "actor": {"actor_id": "test", "session_id": "preflight-box"},
            "target": {"kind": "global", "project_id": project},
            "payload": payload,
            "preconditions": {},
            "options": {},
        },
        headers=headers,
    )


def _merge(client, headers, assignments: dict):
    payload = {"project": "yoke", "environment": "stage", "assignments": assignments}
    return _call(client, headers, MERGE, payload)


def _assert_denied(response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "permission_denied"


def test_role_carries_items_read_and_the_receipt_grant_only() -> None:
    assert set(ROLE_PERMISSION_KEYS[ROLE_PREFLIGHT_EXECUTOR]) == {
        PERM_ITEMS_READ,
        PERM_FLEET_REHEARSAL_RECORD,
    }
    assert PERM_FLEET_REHEARSAL_RECORD in ROLE_PERMISSION_KEYS[ROLE_OWNER]
    assert PERM_FLEET_REHEARSAL_RECORD in ROLE_PERMISSION_KEYS[ROLE_ADMIN]
    assert PERM_FLEET_REHEARSAL_RECORD not in ROLE_PERMISSION_KEYS[ROLE_DEPLOYMENT_CI]


def test_role_is_machine_only() -> None:
    assert ROLE_PREFLIGHT_EXECUTOR in MACHINE_ONLY_ROLES
    with pytest.raises(ActorRoleRefused) as refused:
        require_human_org_role(ROLE_PREFLIGHT_EXECUTOR)
    assert refused.value.code == "machine_only_role"


@pytest.mark.parametrize(
    "assignments",
    [
        {},
        {"release.fleet_rehearsal": {}},
        {"release.fleet_rehearsal.": 1},
        {"release.fleet_rehearsal..x": 1},
        {"release.fleet_rehearsalx.y": 1},
        {RECEIPT_PATH: "r", "release.yoke_pin": "x"},
    ],
)
def test_only_paths_strictly_inside_the_namespace_narrow(assignments) -> None:
    payload = {"assignments": assignments}
    assert not is_fleet_rehearsal_merge(MERGE, payload)


def test_executor_reads_release_settings(client, release_pin_db) -> None:
    headers = _headers(release_pin_db["db_path"])
    response = _call(
        client,
        headers,
        "projects.environment_settings.get",
        {"project": "yoke", "environment": "stage", "paths": ["release.yoke_pin"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["values"] == {"release.yoke_pin": "untouched"}


def test_executor_records_a_receipt_and_leaves_other_keys(
    client, release_pin_db
) -> None:
    headers = _headers(release_pin_db["db_path"])
    response = _merge(
        client,
        headers,
        {RECEIPT_PATH: "fleet-run-1", "release.fleet_rehearsal.yoke.entries": ["a"]},
    )
    assert response.status_code == 200, response.text
    stored = _stored_settings(release_pin_db["db_path"])
    assert stored["release"] == {
        "yoke_pin": "untouched",
        "fleet_rehearsal": {"yoke": {"run": "fleet-run-1", "entries": ["a"]}},
    }
    assert stored["unrelated"] is True


@pytest.mark.parametrize(
    "assignments",
    [
        {"unrelated": False},
        {"release.yoke_pin": "hijacked"},
        {"release.fleet_rehearsal": {"yoke": {}}},
        {RECEIPT_PATH: "r", "delivery.engine_version": "hijacked"},
    ],
)
def test_executor_is_refused_on_any_other_settings_key(
    client, release_pin_db, assignments
) -> None:
    before = _stored_settings(release_pin_db["db_path"])
    _assert_denied(_merge(client, _headers(release_pin_db["db_path"]), assignments))
    assert _stored_settings(release_pin_db["db_path"]) == before


def test_executor_is_refused_on_admin_and_release_operations(
    client, release_pin_db
) -> None:
    headers = _headers(release_pin_db["db_path"])
    _assert_denied(
        _call(
            client,
            headers,
            "projects.capability_settings.merge",
            {
                "project": "yoke",
                "cap_type": "release_pin",
                "assignments": {"desired_pin_path": "release.yoke_pin"},
            },
        )
    )
    _assert_denied(
        _call(
            client,
            headers,
            "release_pin.record",
            {"project": "yoke", "environment": "stage", "pin": "0.0.1"},
        )
    )


def test_executor_grant_stays_on_its_project(client, release_pin_db) -> None:
    headers = _headers(release_pin_db["db_path"])
    response = _call(
        client,
        headers,
        MERGE,
        {
            "project": "externalwebapp",
            "environment": "customer-east",
            "assignments": {RECEIPT_PATH: "r"},
        },
        project="externalwebapp",
    )
    assert response.status_code == 403, response.text


def test_project_admin_still_records_receipts(client, release_pin_db) -> None:
    response = _merge(client, {}, {RECEIPT_PATH: "owner-run"})
    assert response.status_code == 200, response.text

# ruff: noqa: F811
"""Tenant identity and scalar-leaf safety for release-pin recording."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_api_release_pin_record_route import (
    _envelope,
    _stored_settings,
    client,  # noqa: F401 -- fixture imported for this companion module
    release_pin_db,  # noqa: F401 -- fixture imported for this companion module
)
from yoke_core.domain.actor_permissions import (
    ROLE_DEPLOYMENT_CI,
    ROLE_OWNER,
    grant_actor_project_role,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token


@pytest.mark.parametrize("container", ({"nested": "value"}, ["value"]))
def test_record_refuses_to_replace_a_configured_container_leaf(
    client,
    release_pin_db,
    container,
) -> None:
    before = {
        "delivery": {"engine_version": container},
        "unrelated": True,
    }
    with connect_test_db(release_pin_db["db_path"]) as conn:
        conn.execute(
            "UPDATE environments SET settings=%s "
            "WHERE project_id=1 AND name='stage'",
            (json.dumps(before),),
        )
        conn.commit()

    response = client.post("/v1/functions/call", json=_envelope())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "configured_leaf_not_scalar"
    assert _stored_settings(release_pin_db["db_path"]) == before


def test_duplicate_slug_records_only_the_authorized_tenant_environment(
    client,
    release_pin_db,
) -> None:
    db_path = release_pin_db["db_path"]
    with connect_test_db(db_path) as conn:
        conn.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_slug_key")
        conn.execute(
            "INSERT INTO organizations (id, slug, name, created_at) VALUES "
            "(2, 'tenant-two', 'Tenant Two', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix, org_id, "
            "created_at) VALUES (42, 'externalwebapp', 'Tenant Two App', "
            "'TWO', 2, '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO sites (id, project_id, name, created_at) VALUES "
            "(103, 42, 'Tenant Two API', '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO environments "
            "(id, site, project_id, name, settings, created_at) "
            "VALUES (203, 103, 42, 'customer-east', %s, "
            "'2026-01-01T00:00:00Z')",
            (
                json.dumps(
                    {
                        "delivery": {"component_pin": "build-42"},
                        "monitoring": {"status_url": "https://customer.example/status"},
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO project_capabilities "
            "(project_id, type, settings, created_at) VALUES "
            "(42, 'release_pin', %s, '2026-01-01T00:00:00Z')",
            (
                json.dumps(
                    {
                        "desired_pin_path": "delivery.component_pin",
                    }
                ),
            ),
        )
        actor_id = seed_human_actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=42,
            role_name=ROLE_DEPLOYMENT_CI,
            granted_by_actor_id=actor_id,
        )
        token = mint_token(
            conn,
            actor_id=actor_id,
            name="tenant-two-deployment",
        )
        owner_id = seed_human_actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=owner_id,
            project_id=42,
            role_name=ROLE_OWNER,
            granted_by_actor_id=owner_id,
        )
        owner_token = mint_token(
            conn,
            actor_id=owner_id,
            name="tenant-two-owner",
        )
        conn.commit()

    settings_envelope = _envelope(project="externalwebapp")
    settings_envelope["target"] = {"kind": "global"}
    settings_envelope["function"] = "projects.capability_settings.merge"
    settings_envelope["payload"] = {
        "project": "externalwebapp",
        "cap_type": "release_pin",
        "assignments": {
            "probe_url_path": "monitoring.status_url",
            "served_pin_response_path": "build.release",
        },
    }
    owner_headers = {"Authorization": f"Bearer {owner_token.raw_token}"}
    configured = client.post(
        "/v1/functions/call",
        json=settings_envelope,
        headers=owner_headers,
    )
    assert configured.status_code == 200

    settings_envelope["function"] = "projects.capability_settings.get"
    settings_envelope["payload"].pop("assignments")
    capability = client.post(
        "/v1/functions/call",
        json=settings_envelope,
        headers=owner_headers,
    )
    assert capability.status_code == 200
    assert (
        json.loads(capability.json()["result"]["settings_json"])[
            "served_pin_response_path"
        ]
        == "build.release"
    )

    settings_envelope["function"] = "projects.environment_settings.get"
    settings_envelope["payload"] = {
        "project": "externalwebapp",
        "environment": "customer-east",
        "paths": ["delivery.component_pin", "monitoring.status_url"],
    }
    environment = client.post(
        "/v1/functions/call",
        json=settings_envelope,
        headers=owner_headers,
    )
    assert environment.status_code == 200
    assert environment.json()["result"]["values"] == {
        "delivery.component_pin": "build-42",
        "monitoring.status_url": "https://customer.example/status",
    }

    response = client.post(
        "/v1/functions/call",
        json=_envelope(
            project="externalwebapp",
            environment="customer-east",
            pin="build-43",
        ),
        headers={"Authorization": f"Bearer {token.raw_token}"},
    )

    assert response.status_code == 200
    assert response.json()["result"] == {
        "project": "externalwebapp",
        "environment": "customer-east",
        "settings_path": "delivery.component_pin",
        "pin": "build-43",
        "changed": True,
    }
    assert _stored_settings(db_path, "customer-east", 42) == {
        "delivery": {"component_pin": "build-43"},
        "monitoring": {"status_url": "https://customer.example/status"},
    }
    assert _stored_settings(db_path, "customer-east", 2) == {}
    with connect_test_db(db_path) as conn:
        cross_tenant_capability = conn.execute(
            "SELECT settings FROM project_capabilities "
            "WHERE project_id=2 AND type='release_pin'"
        ).fetchone()
    assert cross_tenant_capability is None

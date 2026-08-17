"""UI proxy coverage for the metadata-only Delivery infrastructure read."""

from __future__ import annotations

from runtime.api.universe_ui_server_test_support import (
    _TOKEN,
    ui_client as ui_client,
)
from yoke_core.ui import server as ui_server


def _call(ui_client, envelope):
    return ui_client.post(
        f"/api/functions/call?token={_TOKEN}",
        json=envelope,
    )


def test_project_infrastructure_read_is_admitted_and_metadata_only(
    ui_client,
    test_db,
):
    projects = _call(
        ui_client,
        {
            "function": "projects.list",
            "payload": {"fields": ["id", "slug", "name"]},
        },
    ).json()["result"]["rows"]
    project_id = str(projects[0]["id"])
    # The shared fixture owns both tables; add only the metadata leaf this
    # focused read exercises but the compact environment schema omits.
    test_db.execute(
        "ALTER TABLE environments ADD COLUMN IF NOT EXISTS deploy_method TEXT"
    )
    test_db.execute(
        "ALTER TABLE environments ADD COLUMN IF NOT EXISTS last_deployed_at TEXT"
    )
    test_db.execute(
        "DELETE FROM environments WHERE site IN "
        "(SELECT id FROM sites WHERE project_id=%s)",
        (int(project_id),),
    )
    test_db.execute(
        "DELETE FROM sites WHERE project_id=%s",
        (int(project_id),),
    )
    test_db.execute(
        "INSERT INTO sites (id, project_id, name, description, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            "ui-app",
            int(project_id),
            "Application",
            "UI delivery proof",
            "2026-01-01T00:00:00Z",
        ),
    )
    test_db.execute(
        "INSERT INTO environments ("
        "id, site, name, url, deploy_method, health_check_url, settings, "
        "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            "ui-prod",
            "ui-app",
            "Production",
            "https://example.test",
            "github-actions",
            "https://example.test/health",
            '{"git":{"branch":"main"},"deploy":{"automatic":true}}',
            "2026-01-01T00:00:00Z",
        ),
    )
    test_db.commit()

    response = _call(
        ui_client,
        {
            "function": "projects.infrastructure.list",
            "payload": {"project": project_id},
        },
    )

    assert response.status_code == 200
    envelope = response.json()
    assert envelope["success"] is True
    assert envelope["result"] == {
        "project": project_id,
        "sites": [{
            "id": "ui-app",
            "name": "Application",
            "description": "UI delivery proof",
        }],
        "environments": [{
            "id": "ui-prod",
            "site": "ui-app",
            "name": "Production",
            "url": "https://example.test",
            "deploy_method": "github-actions",
            "health_check_url": "https://example.test/health",
            "last_deployed_at": None,
        }],
    }
    assert "projects.infrastructure.list" in ui_server.UI_READ_FUNCTION_ALLOWLIST
    assert (
        "projects.infrastructure.list"
        not in ui_server.UI_MUTATION_FUNCTION_ALLOWLIST
    )

    settings_response = _call(
        ui_client,
        {
            "function": "projects.environment_settings.get",
            "payload": {
                "project": project_id,
                "environment_id": "ui-prod",
                "paths": ["git.branch"],
            },
        },
    )

    assert settings_response.status_code == 200
    settings_envelope = settings_response.json()
    assert settings_envelope["success"] is True
    assert settings_envelope["result"] == {
        "project": project_id,
        "environment_id": "ui-prod",
        "values": {"git.branch": "main"},
    }
    assert (
        "projects.environment_settings.get"
        in ui_server.UI_READ_FUNCTION_ALLOWLIST
    )
    assert (
        "projects.environment_settings.get"
        not in ui_server.UI_MUTATION_FUNCTION_ALLOWLIST
    )

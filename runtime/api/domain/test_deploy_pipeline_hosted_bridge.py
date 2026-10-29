"""Hosted dispatch endpoints follow the owning connection and fail closed."""

import pytest

from yoke_core.domain import deploy_pipeline_hosted_bridge as bridge


@pytest.mark.parametrize("owner", ["stage", "prod"])
@pytest.mark.parametrize("admin", [False, True])
def test_owner_connection_supplies_endpoint(monkeypatch, owner, admin):
    monkeypatch.setenv("YOKE_ENV", owner + ("-db-admin" if admin else ""))
    endpoint = f"https://{owner}.example/api/orgs/team"
    monkeypatch.setattr(
        bridge.machine_config,
        "load_config",
        lambda: {
            "connections": {
                owner: {"transport": "https", "api_url": endpoint},
                owner + "-db-admin": {"transport": "local-postgres"},
            },
        },
    )
    values, diagnostic = bridge.hosted_bridge_inputs(
        "platform-release-bridge.yml",
        {"control_plane_api_url": "https://wrong.example"},
    )
    assert diagnostic == ""
    assert values["control_plane_api_url"] == endpoint


@pytest.mark.parametrize(
    "connection",
    [
        {"transport": "local-postgres"},
        {"transport": "https", "api_url": ""},
        {"transport": "https", "api_url": "https://secret@example.com/api"},
        {"transport": "https", "api_url": "http://example.com/api"},
    ],
)
def test_missing_or_unsafe_owner_endpoint_refuses(monkeypatch, connection):
    monkeypatch.setenv("YOKE_ENV", "stage-db-admin")
    monkeypatch.setattr(
        bridge.machine_config,
        "load_config",
        lambda: {
            "connections": {"stage-db-admin": connection},
        },
    )
    values, diagnostic = bridge.hosted_bridge_inputs("platform-release-bridge.yml", {})
    assert values == {}
    assert diagnostic.startswith("release_control_endpoint_unavailable:")
    assert "secret" not in diagnostic


def test_other_workflows_need_no_hosted_connection(monkeypatch):
    def unexpected():
        pytest.fail("a customer workflow must not inspect hosted authority")

    monkeypatch.setattr(bridge.machine_config, "load_config", unexpected)
    assert bridge.hosted_bridge_inputs("deploy.yml", {"target": "local"}) == (
        {"target": "local"},
        "",
    )

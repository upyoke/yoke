"""Transport-aware loading for deploy-time project renderer settings."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.commands import pulumi_stack_config_loader as loader
from yoke_cli.transport.https import HttpsConnection
from yoke_core.domain import project_renderer_settings
from yoke_core.domain.project_renderer_settings_snapshot import STACK_CONFIG_SCHEMA


def _payload(project: str = "customer app") -> dict:
    return {
        "config_schema": STACK_CONFIG_SCHEMA,
        "project_id": 41,
        "project_slug": project,
        "renderer_settings": {
            "project": project,
            "deploy_namespace": "customer",
            "display_name": "Customer App",
            "site": "Customer API",
            "site_settings": {},
            "environments": [
                {
                    "name": "prod",
                    "settings": {"hosts": {"api": "api.customer.test"}},
                }
            ],
            "capabilities": {},
        },
    }


def test_https_snapshot_uses_authenticated_aggregate_route(monkeypatch):
    connection = HttpsConnection(
        api_url="https://control.example/v1/",
        token="secret-token",
        env="prod",
    )
    observed = {}

    def request_json(request, **kwargs):
        observed["url"] = request.full_url
        observed["authorization"] = request.get_header("Authorization")
        observed["kwargs"] = kwargs
        return SimpleNamespace(payload=_payload())

    monkeypatch.setattr(loader, "resolve_https_connection", lambda: connection)
    monkeypatch.setattr(loader, "request_json", request_json)

    result = loader.load_project_renderer_settings_snapshot("customer app")

    assert result == _payload()
    assert observed["url"].endswith(
        "/v1/projects/customer%20app/pulumi-stack-config"
    )
    assert observed["authorization"] == "Bearer secret-token"
    assert observed["kwargs"]["replay_safe"] is True
    assert observed["kwargs"]["sensitive_values"] == ("secret-token",)


def test_public_loader_hydrates_transport_snapshot(monkeypatch):
    monkeypatch.setattr(
        loader,
        "load_project_renderer_settings_snapshot",
        lambda _project: _payload("customer"),
    )

    settings = project_renderer_settings.load_project_renderer_settings("customer")

    assert settings.project == "customer"
    assert settings.deploy_namespace == "customer"
    assert settings.environments[0].name == "prod"
    assert settings.environments[0].settings["hosts"]["api"] == (
        "api.customer.test"
    )

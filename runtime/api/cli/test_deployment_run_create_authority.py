"""The execute recipe names authority only after resolving the target host."""

from __future__ import annotations

import pytest

from yoke_cli.commands.adapters import deployment_execution_authority as authority
from yoke_cli.commands.adapters import deployment_run_create
from yoke_cli.transport.https import HttpsConnection, TransportError
from yoke_contracts.machine_config.schema import ENV_OVERRIDE


@pytest.fixture
def boundaries(monkeypatch):
    from yoke_cli.commands import pulumi_stack_config_loader as settings
    from yoke_cli.config import machine_config
    from yoke_cli.transport import https

    monkeypatch.setenv(ENV_OVERRIDE, "prod")
    monkeypatch.setattr(
        https,
        "resolve_https_connection",
        lambda: HttpsConnection(
            api_url="https://control.example/v1", token="token", env="prod"
        ),
    )
    monkeypatch.setattr(
        authority,
        "_run",
        lambda _id: {"project": "customer", "target_environment": "prod"},
    )
    monkeypatch.setattr(
        machine_config,
        "load_config",
        lambda: {"connections": {"prod-db-admin": {"transport": "local-postgres"}}},
    )

    def host(value):
        monkeypatch.setattr(
            settings,
            "load_project_renderer_settings_snapshot",
            lambda _p: {
                "renderer_settings": {
                    "environments": [
                        {"name": "prod", "settings": {"hosts": {"api": value}}}
                    ]
                }
            },
        )

    host("api.customer.example")
    return host, https, settings


@pytest.mark.parametrize("active", ["prod", "stage", "  prod  ", "prod-db-admin"])
def test_another_host_keeps_the_selected_connection(boundaries, monkeypatch, active):
    monkeypatch.setenv(ENV_OVERRIDE, active)
    assert deployment_run_create._execute_connection("run-1") == active.strip()


def test_same_host_names_the_paired_admin_connection(boundaries):
    host, _, _ = boundaries
    host("CONTROL.EXAMPLE.")
    assert deployment_run_create._execute_connection("run-1") == "prod-db-admin"


@pytest.mark.parametrize("boundary", ["connection", "run", "settings"])
def test_resolution_failure_keeps_the_placeholder(boundaries, monkeypatch, boundary):
    _, https, settings = boundaries

    def fail(*_args):
        raise TransportError("unavailable")

    owner, name = {
        "connection": (https, "resolve_https_connection"),
        "run": (authority, "_run"),
        "settings": (settings, "load_project_renderer_settings_snapshot"),
    }[boundary]
    monkeypatch.setattr(owner, name, fail)
    assert deployment_run_create._execute_connection("run-1") == ""


def test_unknown_target_host_keeps_the_placeholder(boundaries):
    host, _, _ = boundaries
    host("")
    assert deployment_run_create._execute_connection("run-1") == ""


@pytest.mark.parametrize("active", [None, "   "])
def test_absent_connection_keeps_the_placeholder(monkeypatch, active):
    if active is None:
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
    else:
        monkeypatch.setenv(ENV_OVERRIDE, active)
    assert deployment_run_create._execute_connection("run-1") == ""

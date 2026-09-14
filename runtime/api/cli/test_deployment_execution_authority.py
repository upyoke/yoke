"""Deployment execution distinguishes customer delivery from self-deploy."""

from __future__ import annotations

from unittest import mock

from yoke_cli.commands.adapters import deployment_execution_authority as authority
from yoke_cli.transport.https import HttpsConnection, TransportError


def _snapshot(host: str) -> dict:
    return {
        "renderer_settings": {
            "environments": [
                {"name": "prod", "settings": {"hosts": {"api": host}}}
            ]
        }
    }


def _https() -> HttpsConnection:
    return HttpsConnection(
        api_url="https://control.example/v1",
        token="token",
        env="prod",
    )


def _run() -> dict:
    return {"project": "customer", "target_environment": "prod"}


def test_local_control_plane_needs_no_extra_gate():
    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection", return_value=None
    ):
        assert authority.execution_connection_error("run-1") is None


def test_external_customer_target_executes_through_https():
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_https(),
        ),
        mock.patch.object(authority, "_run", return_value=_run()),
        mock.patch(
            "yoke_cli.commands.pulumi_stack_config_loader."
            "load_project_renderer_settings_snapshot",
            return_value=_snapshot("api.customer.example"),
        ),
    ):
        assert authority.execution_connection_error("run-1") is None


def test_self_deploy_requires_same_universe_admin_connection():
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_https(),
        ),
        mock.patch.object(authority, "_run", return_value=_run()),
        mock.patch.object(
            authority, "_same_universe_admin_env", return_value="prod-db-admin"
        ),
        mock.patch(
            "yoke_cli.commands.pulumi_stack_config_loader."
            "load_project_renderer_settings_snapshot",
            return_value=_snapshot("CONTROL.EXAMPLE."),
        ),
    ):
        refusal = authority.execution_connection_error("run-1")

    assert refusal is not None
    assert "self-deployment" in refusal
    assert "prod-db-admin" in refusal
    assert "run-1" in refusal


def test_unregistered_target_host_is_not_guessed_as_self_deploy():
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_https(),
        ),
        mock.patch.object(authority, "_run", return_value=_run()),
        mock.patch(
            "yoke_cli.commands.pulumi_stack_config_loader."
            "load_project_renderer_settings_snapshot",
            return_value=_snapshot(""),
        ),
    ):
        assert authority.execution_connection_error("run-1") is None


def test_broken_https_connection_reports_its_actual_failure():
    with mock.patch(
        "yoke_cli.transport.https.resolve_https_connection",
        side_effect=TransportError("token missing"),
    ):
        refusal = authority.execution_connection_error("run-1")

    assert refusal is not None
    assert "token missing" in refusal

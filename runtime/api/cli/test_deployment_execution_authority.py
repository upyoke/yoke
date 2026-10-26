"""Deployment execution distinguishes customer delivery from self-deploy."""

from __future__ import annotations

from unittest import mock

from yoke_cli.commands.adapters import deployment_execution_authority as authority
from yoke_cli.transport.https import HttpsConnection, TransportError


def _snapshot(host: str) -> dict:
    return {
        "renderer_settings": {
            "environments": [{"name": "prod", "settings": {"hosts": {"api": host}}}]
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
    assert "`yoke --env prod-db-admin watch deploy -- run-1`" in refusal


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


def _creation_calls(function_id, target, payload):
    if function_id == "items.detail.get":
        return {
            "item": {
                "project": {"slug": "customer"},
                "deployment_flow": {"value": "to-prod"},
            }
        }
    assert payload == {"project": "customer", "flow": "to-prod"}
    return {"target_environment_name": "prod"}


def test_creation_refuses_a_run_this_connection_could_not_drive():
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_https(),
        ),
        mock.patch.object(authority, "_call", side_effect=_creation_calls),
        mock.patch.object(authority, "_same_universe_admin_env", return_value=""),
        mock.patch(
            "yoke_cli.commands.pulumi_stack_config_loader."
            "load_project_renderer_settings_snapshot",
            return_value=_snapshot("control.example"),
        ),
    ):
        refusal = authority.creation_connection_error(
            "start-for-item ITEM-1",
            project=None,
            flow=None,
            environment=None,
            item="ITEM-1",
        )

    assert refusal is not None
    assert "owner-only local-postgres connection" in refusal
    assert "nothing was created" in refusal
    assert "yoke say --stdin --steering" in refusal


def test_creation_over_https_is_allowed_with_the_paired_admin_connection():
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_https(),
        ),
        mock.patch.object(authority, "_call", side_effect=_creation_calls),
        mock.patch.object(
            authority, "_same_universe_admin_env", return_value="prod-db-admin"
        ),
        mock.patch(
            "yoke_cli.commands.pulumi_stack_config_loader."
            "load_project_renderer_settings_snapshot",
            return_value=_snapshot("control.example"),
        ),
    ):
        assert (
            authority.creation_connection_error(
                "create customer to-prod",
                project="customer",
                flow="to-prod",
                environment=None,
            )
            is None
        )


def test_creation_leaves_an_unresolvable_target_to_the_server_refusal():
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=_https(),
        ),
        mock.patch.object(authority, "_call", side_effect=RuntimeError("unknown flow")),
    ):
        assert (
            authority.creation_connection_error(
                "create", project="customer", flow="missing", environment=None
            )
            is None
        )

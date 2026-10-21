"""Routine functions refuse a ``*-db-admin`` door whose https env serves them.

Through the door each handler runs on this machine and every query is a
round trip to the database, so a routine call names the https env that
serves the same control plane. Diagnostics, repairs and the declared
direct-database commands still run through the door.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from yoke_cli.commands import deployment_execute
from yoke_cli.commands.adapters import deployment_execution_authority as authority
from yoke_cli.transport import dispatcher
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts import direct_database_access as door
from yoke_contracts.api.function_call import TargetRef

ADMIN_ENV = "prod-db-admin"
SERVED_ENV = "prod"
PAIRED = {
    "connections": {
        ADMIN_ENV: {"transport": "local-postgres", "prod": True},
        SERVED_ENV: {"transport": "https", "api_url": "https://control.example/v1"},
    }
}


@pytest.fixture
def select(monkeypatch):
    monkeypatch.delenv(door.DECLARED_COMMAND_ENV, raising=False)

    def _select(env: str, config: dict[str, Any]) -> None:
        runtime = door.machine_config_runtime
        monkeypatch.setattr(runtime, "active_env", lambda **_kwargs: env)
        monkeypatch.setattr(runtime, "load_config", lambda *_a, **_kw: config)

    return _select


@pytest.fixture
def local_calls(monkeypatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(
        dispatcher.https_transport, "resolve_https_connection", lambda **_kw: None
    )
    monkeypatch.setattr(
        dispatcher.local_github_dispatch,
        "call_with_machine_github_authorization",
        lambda request, dispatch, core_available: dispatch(request),
    )
    return seen


def _call(function_id: str, seen: list[str]):
    def local_dispatch(request: Any) -> Any:
        seen.append(request.function)
        return dispatcher._error_response(request, "stub", "stub")

    return dispatcher.call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload={},
        _local_dispatch=local_dispatch,
    )


def test_routine_function_on_the_door_refuses_naming_the_https_env(
    select, local_calls
):
    select(ADMIN_ENV, PAIRED)

    response = _call("deployment_runs.create", local_calls)

    assert local_calls == []
    assert response.error is not None
    assert response.error.code == "use_https_env"
    assert repr(SERVED_ENV) in response.error.message
    assert f"--env {SERVED_ENV}`" in response.error.recovery_hint


@pytest.mark.parametrize("function_id", sorted(door.DIRECT_DATABASE_FUNCTIONS))
def test_listed_direct_database_function_still_runs_on_the_door(
    select, local_calls, function_id
):
    select(ADMIN_ENV, PAIRED)

    _call(function_id, local_calls)

    assert local_calls == [function_id]


def test_declared_direct_database_command_keeps_the_door(select, local_calls):
    select(ADMIN_ENV, PAIRED)
    with door.direct_database_command(door.MIGRATION_REHEARSE_COMMAND):
        _call("projects.environment_settings.get", local_calls)
    assert door.DECLARED_COMMAND_ENV not in os.environ

    assert local_calls == ["projects.environment_settings.get"]


@pytest.mark.parametrize(
    ("env", "config"),
    [
        (ADMIN_ENV, {"connections": {ADMIN_ENV: {"transport": "local-postgres"}}}),
        ("local", {"connections": {"local": {"transport": "local-postgres"}}}),
    ],
)
def test_door_without_https_env_and_local_universe_run_locally(
    select, local_calls, env, config
):
    select(env, config)

    _call("deployment_runs.create", local_calls)

    assert local_calls == ["deployment_runs.create"]


def test_undeclared_command_cannot_be_declared():
    with pytest.raises(ValueError):
        door.direct_database_environment("items create")


def _snapshot(host: str) -> dict:
    return {
        "renderer_settings": {
            "environments": [{"name": "prod", "settings": {"hosts": {"api": host}}}]
        }
    }


@pytest.mark.parametrize(
    ("host", "refused"), [("control.example", False), ("api.customer.example", True)]
)
def test_door_drives_only_a_deploy_replacing_its_https_api(host, refused):
    connection = HttpsConnection(
        api_url="https://control.example/v1", token="token", env=SERVED_ENV
    )
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=connection,
        ),
        mock.patch.object(
            authority,
            "_run",
            return_value={"project": "yoke", "target_environment": "prod"},
        ) as run,
        mock.patch(
            "yoke_cli.commands.pulumi_stack_config_loader."
            "load_project_renderer_settings_snapshot",
            return_value=_snapshot(host),
        ),
    ):
        refusal = authority.door_execution_error("run-1", SERVED_ENV)

    assert run.call_args.kwargs == {"relay_env": SERVED_ENV}
    if not refused:
        assert refusal is None
        return
    assert refusal is not None
    assert refusal.startswith("use_https_env:")
    assert f"yoke --env {SERVED_ENV} deployment-runs execute run-1" in refusal


def test_self_deploy_driver_inherits_the_declared_door(monkeypatch):
    monkeypatch.delenv(door.DECLARED_COMMAND_ENV, raising=False)
    monkeypatch.setattr(deployment_execute, "paired_https_env", lambda: SERVED_ENV)
    monkeypatch.setattr(deployment_execute, "door_execution_error", lambda *_a: None)
    inherited: list[str | None] = []

    def run(*_args, **_kwargs):
        inherited.append(os.environ.get(door.DECLARED_COMMAND_ENV))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(deployment_execute.subprocess, "run", run)

    assert deployment_execute.deployment_runs_execute(["run-1"]) == 0

    assert inherited == [door.SELF_DEPLOY_EXECUTE_COMMAND]
    assert door.DECLARED_COMMAND_ENV not in os.environ


@pytest.mark.parametrize(
    ("failure", "allowed"),
    [
        (authority._RunReadFailed("unreachable", code="https_transport_failed"), True),
        (authority._RunReadFailed("no such run", code="not_found"), False),
    ],
)
def test_unreachable_https_env_allows_the_door_with_a_note(failure, allowed, capsys):
    connection = HttpsConnection(
        api_url="https://control.example/v1", token="token", env=SERVED_ENV
    )
    with (
        mock.patch(
            "yoke_cli.transport.https.resolve_https_connection",
            return_value=connection,
        ),
        mock.patch.object(authority, "_run", side_effect=failure),
    ):
        refusal = authority.door_execution_error("run-1", SERVED_ENV)

    note = capsys.readouterr().err
    if allowed:
        assert refusal is None
        assert f"note: {SERVED_ENV!r} cannot be reached" in note
        assert "self-deploy recovery" in note
    else:
        assert refusal == "no such run"
        assert note == ""


@pytest.mark.parametrize(
    ("argv", "bootstrap"),
    [
        (["--env", ADMIN_ENV, "deployment-runs", "create", "yoke", "FLOW"], True),
        (["--env", ADMIN_ENV, "deployment-runs", "get", "run-1"], False),
        (["items", "create"], False),
    ],
)
def test_explicit_launcher_declares_only_creation_bootstrap(argv, bootstrap):
    from yoke_core.tools import yoke_launcher

    assert yoke_launcher._is_creation_bootstrap(argv) is bootstrap


def test_relay_refuses_a_non_prod_door_whose_https_env_serves_it(tmp_path):
    import json

    from yoke_cli.config.session_relay_instance import (
        RelayInstanceError,
        resolve_relay_instance,
    )

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "stage",
                "connections": {
                    "stage": {
                        "transport": "https",
                        "api_url": "https://stage.example.test",
                        "credential_source": {
                            "kind": "token_file",
                            "path": "~/.yoke/secrets/stage.token",
                        },
                    },
                    "stage-db-admin": {
                        "transport": "local-postgres",
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": "~/.yoke/secrets/stage-db-admin.dsn",
                        },
                    },
                },
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RelayInstanceError, match="use_https_env") as raised:
        resolve_relay_instance(
            config_path=config, environment="stage-db-admin", yoke_home=tmp_path
        )
    assert "yoke --env stage relay install" in str(raised.value)

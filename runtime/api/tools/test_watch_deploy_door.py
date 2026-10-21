"""Every deploy driver entry holds the self-deploy door on a `*-db-admin` door.

`yoke --env prod-db-admin watch deploy` declares it for its own attachment,
liveness and children. The engine modules declare it themselves too, so a
driver started by an older CLI that sets nothing still reaches the database.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from yoke_cli.commands.adapters import deployment_execution_authority as authority
from yoke_cli.transport import dispatcher
from yoke_contracts import direct_database_access as door
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import deploy_pipeline_driver_client as driver_client
from yoke_core.domain import deploy_pipeline_cli, deploy_pipeline_liveness_cli
from yoke_core.tools import watch_deploy

pytestmark = pytest.mark.usefixtures("bound_project_context")

ADMIN_ENV = "prod-db-admin"
SERVED_ENV = "prod"
PAIRED = {
    "connections": {
        ADMIN_ENV: {"transport": "local-postgres", "prod": True},
        SERVED_ENV: {"transport": "https", "api_url": "https://control.example/v1"},
    }
}


@pytest.fixture
def on_the_door(monkeypatch, tmp_path) -> list[str]:
    monkeypatch.delenv(door.DECLARED_COMMAND_ENV, raising=False)
    runtime = door.machine_config_runtime
    monkeypatch.setattr(runtime, "active_env", lambda **_kwargs: ADMIN_ENV)
    monkeypatch.setattr(runtime, "load_config", lambda *_a, **_kw: PAIRED)
    monkeypatch.setattr(
        dispatcher.https_transport, "resolve_https_connection", lambda **_kw: None
    )
    dispatched: list[str] = []

    def local(request: Any, _dispatch: Any, core_available: bool) -> Any:
        dispatched.append(request.function)
        return FunctionCallResponse(
            success=True,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            result={},
        )

    monkeypatch.setattr(
        dispatcher.local_github_dispatch,
        "call_with_machine_github_authorization",
        local,
    )
    monkeypatch.setattr(
        watch_deploy._watch_runner,
        "bind_capture_paths",
        lambda ns, kind: (tmp_path / "raw", tmp_path / "progress"),
    )
    return dispatched


def test_self_deploy_watch_attaches_and_children_keep_the_door(
    monkeypatch, on_the_door
):
    door_checks: list[tuple[str, str]] = []
    monkeypatch.setattr(
        authority,
        "door_execution_error",
        lambda run_id, https_env: door_checks.append((run_id, https_env)),
    )
    monkeypatch.setattr(
        watch_deploy,
        "child_environment",
        lambda _run_id: {**os.environ, "YOKE_DEPLOY_DRIVER_RELEASE": "abc"},
    )
    captured: dict[str, Any] = {}

    def run_watcher(**kwargs: Any) -> int:
        captured.update(kwargs)
        captured["inherited"] = os.environ.get(door.DECLARED_COMMAND_ENV)
        return 0

    monkeypatch.setattr(watch_deploy._watch_runner, "run_watcher", run_watcher)
    monkeypatch.setattr(driver_client, "_local_machine_id", lambda: "machine-1")

    assert watch_deploy.main(["run-1"]) == 0

    assert door_checks == [("run-1", SERVED_ENV)]
    assert driver_client.ATTACH_FUNCTION_ID in on_the_door
    assert captured["env"][door.DECLARED_COMMAND_ENV] == (
        door.SELF_DEPLOY_EXECUTE_COMMAND
    )
    assert captured["inherited"] == door.SELF_DEPLOY_EXECUTE_COMMAND
    assert door.DECLARED_COMMAND_ENV not in os.environ


def test_door_refuses_a_run_it_does_not_self_deploy(monkeypatch, on_the_door):
    monkeypatch.setattr(
        authority,
        "door_execution_error",
        lambda run_id, https_env: f"use_https_env: rerun with --env {https_env}",
    )
    reports: list[str] = []
    monkeypatch.setattr(
        watch_deploy,
        "_report_preflight_failure",
        lambda message, *_a: reports.append(message) or 2,
    )

    assert watch_deploy.main(["run-1"]) == 2

    assert reports == ["watch_deploy: use_https_env: rerun with --env prod"]
    assert on_the_door == []


@pytest.fixture
def self_deploy(monkeypatch, on_the_door):
    monkeypatch.setattr(authority, "door_execution_error", lambda *_a: None)
    monkeypatch.setattr(driver_client, "_local_machine_id", lambda: "machine-1")
    return on_the_door


def _attach_and_report(run_id: str, **_kwargs: Any) -> int:
    driver_client.attach_driver(run_id, phase="executing")
    return 0 if os.environ.get(door.DECLARED_COMMAND_ENV) else 9


def test_pipeline_engine_declares_its_own_door(self_deploy):
    assert os.environ.get(door.DECLARED_COMMAND_ENV) is None

    assert deploy_pipeline_cli.main(["run-1"], runner=_attach_and_report) == 0

    assert self_deploy == [driver_client.ATTACH_FUNCTION_ID]
    assert door.DECLARED_COMMAND_ENV not in os.environ


def test_liveness_engine_declares_its_own_door(monkeypatch, self_deploy):
    monkeypatch.setattr(
        deploy_pipeline_liveness_cli, "_reexec_into_pinned_source", lambda _a: None
    )
    monkeypatch.setattr(
        deploy_pipeline_liveness_cli.deploy_pipeline,
        "main",
        lambda argv: _attach_and_report(argv[0]),
    )

    assert deploy_pipeline_liveness_cli.main(["run-1"]) == 0

    assert driver_client.ATTACH_FUNCTION_ID in self_deploy
    assert door.DECLARED_COMMAND_ENV not in os.environ


def test_engine_refuses_a_run_it_does_not_self_deploy(monkeypatch, on_the_door):
    monkeypatch.setattr(
        authority, "door_execution_error", lambda *_a: "use_https_env: rerun"
    )
    ran: list[str] = []

    assert deploy_pipeline_cli.main(["run-1"], runner=lambda *a, **k: ran.append("x")) == 2
    assert ran == [] and on_the_door == []


def test_watcher_helper_reads_ask_the_paired_https_env(monkeypatch, tmp_path):
    from yoke_contracts.api.function_call import ActorContext
    from yoke_core.tools import _watch_wait_mode, watch_tail

    monkeypatch.delenv(door.DECLARED_COMMAND_ENV, raising=False)
    runtime = door.machine_config_runtime
    monkeypatch.setattr(runtime, "active_env", lambda **_kwargs: ADMIN_ENV)
    monkeypatch.setattr(runtime, "load_config", lambda *_a, **_kw: PAIRED)
    relayed: list[tuple[str, Any]] = []

    def call(**kwargs: Any) -> Any:
        relayed.append((kwargs["function_id"], kwargs.get("relay_env")))
        return FunctionCallResponse(
            success=True, function=kwargs["function_id"], version="v1", result={}
        )

    monkeypatch.setattr(watch_tail, "call_dispatcher", call)
    monkeypatch.setattr(_watch_wait_mode, "call_dispatcher", call)
    monkeypatch.setattr(
        _watch_wait_mode,
        "build_actor",
        lambda: ActorContext(actor_id="a", session_id="session-1"),
    )

    watch_tail._live_driver(tmp_path / "progress")
    _watch_wait_mode._current_session_row()

    assert relayed == [
        (watch_tail.FOR_CAPTURE_FUNCTION_ID, SERVED_ENV),
        ("sessions.list", SERVED_ENV),
    ]

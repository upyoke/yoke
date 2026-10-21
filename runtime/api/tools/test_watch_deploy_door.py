"""`yoke --env prod-db-admin watch deploy` drives a self-deploy through the door.

The wrapper runs the pipeline itself rather than through `deployment-runs
execute`, so it declares the self-deploy door for its whole body: the
driver attachment, its liveness pump and every child it starts keep it.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from yoke_cli.transport import dispatcher
from yoke_contracts import direct_database_access as door
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import deploy_pipeline_driver_client as driver_client
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
        watch_deploy,
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
        watch_deploy,
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
